import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/muse-delegate/scripts"
sys.path.insert(0, str(SCRIPTS))
import task_ledger as ledger


def execution(attempt="one", total=None, status="completed"):
    return {"type": "execution", "task_id": "task", "attempt_id": attempt,
            "execution_status": status, "elapsed_seconds": 2,
            "muse_usage": {"input_tokens": None, "output_tokens": None, "total_tokens": total},
            "handoff": None}


def review(attempt="one", decision="accepted"):
    return {"type": "review", "task_id": "task", "attempt_id": attempt,
            "decision": decision, "evidence": "Reviewed diff and focused checks"}


class LedgerTests(unittest.TestCase):
    def test_missing_usage_and_completed_are_not_zero_or_accepted(self):
        result = ledger.summarize_events([execution()])
        self.assertEqual(result["accepted_tasks"], 0)
        self.assertIsNone(result["tasks"][0]["muse_tokens"])
        self.assertIsNone(result["total_cross_provider_tokens"])
        self.assertIsNone(result["primary_tokens_per_accepted_task"])
        self.assertEqual(result["primary_unmeasured_tasks"], 1)

    def test_followups_duplicate_imports_and_latest_review(self):
        events = [execution(total=10), execution(total=10), review(), execution("two", total=20)]
        result = ledger.summarize_events(events)
        self.assertEqual(result["accepted_tasks"], 0)
        self.assertEqual(result["tasks"][0]["additional_attempts"], 1)
        events += [review("two"), {"type": "primary_usage", "task_id": "task", "total_tokens": 100,
                                  "evidence": "Provider measured whole task"}]
        result = ledger.summarize_events(events)
        self.assertEqual(result["primary_tokens_per_accepted_task"], 100)
        self.assertEqual(result["total_cross_provider_tokens"], 130)
        events.append(review("two", "rejected"))
        self.assertEqual(ledger.summarize_events(events)["accepted_tasks"], 0)

    def test_invalid_measurements_failed_acceptance_and_conflicts(self):
        for events in ([execution(status="failed"), review()], [review()],
                       [execution(), execution(total=3)], [execution(total=True)],
                       [execution(total=-1)], [{**execution(), "elapsed_seconds": float("nan")} ]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                ledger.summarize_events(events)

    def test_partial_coverage_does_not_publish_complete_average(self):
        events = [execution(total=10), review(), {"type": "primary_usage", "task_id": "task",
            "total_tokens": 100, "evidence": "measured"},
            {**execution(total=None), "task_id": "other"}, {**review(), "task_id": "other"}]
        result = ledger.summarize_events(events)
        self.assertEqual(result["primary_tokens_per_measured_accepted_task"], 100)
        self.assertEqual(result["primary_measured_accepted_tasks"], 1)
        self.assertEqual(result["accepted_tasks"], 2)
        self.assertIsNone(result["primary_tokens_per_accepted_task"])
        self.assertIsNone(result["total_cross_provider_tokens"])
        self.assertEqual(result["muse_known_tokens"], 10)

    def test_concurrent_appends_duplicate_import_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.jsonl"
            code = ("import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                    "from task_ledger import append_event; append_event(Path(sys.argv[2]),json.loads(sys.argv[3]))")
            jobs = [subprocess.Popen([sys.executable, "-c", code, str(SCRIPTS), str(path), json.dumps(execution(str(i)))])
                    for i in range(4)]
            self.assertEqual([p.wait(timeout=10) for p in jobs], [0] * 4)
            ledger.append_event(path, execution("0"))
            self.assertEqual(ledger.summarize(path)["tasks"][0]["attempts"], 4)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                ledger.append_event(path, review("missing"))
            self.assertEqual(path.read_bytes(), original)
            path.write_text("broken json\n")
            with self.assertRaises(ValueError):
                ledger.summarize(path)
            link = Path(tmp) / "linked"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                ledger.append_event(link, execution())


if __name__ == "__main__":
    unittest.main()
