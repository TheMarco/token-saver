"""Offline checks of actual locks, Git scope evidence, and configuration parsing."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/muse-delegate/scripts"
sys.path.insert(0, str(SCRIPTS))
import muse_evidence as evidence
import muse_worker


class EvidenceTests(unittest.TestCase):
    def test_configuration_unknown_and_mismatch(self):
        self.assertIsNone(evidence.configuration({"model": None, "reasoning_effort": None}, {})["matches_requested"])
        result = evidence.configuration({"model": "requested", "reasoning_effort": "max"}, {"model": "different"})
        self.assertFalse(result["matches_requested"])
        self.assertIsNone(result["matches"]["reasoning_effort"])

    def test_git_changes_include_rename_deletion_untracked_and_preexisting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            def git(*args):
                return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=Test",
                    "-c", "user.email=test@example.com", *args], cwd=root, check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git("init")
            for name in ["keep.txt", "delete.txt", "rename.txt", "dirty.txt"]:
                (root / name).write_text(name)
            git("add", ".")
            git("commit", "-m", "baseline")
            (root / "dirty.txt").write_text("existing user change")
            before = evidence.snapshot(root)
            git("mv", "rename.txt", "renamed.txt")
            (root / "delete.txt").unlink()
            (root / "new\nfile.txt").write_text("untracked")
            after = evidence.snapshot(root)
            result = evidence.change_summary(root, before, after, ["rename.txt", "renamed.txt"], "edit")
            self.assertEqual(result["preexisting_files"], ["dirty.txt"])
            self.assertEqual(result["scope_violations"], ["delete.txt", "new\nfile.txt"])
            self.assertEqual(result["changed_files"], ["delete.txt", "new\nfile.txt", "rename.txt", "renamed.txt"])
            self.assertEqual(result["untracked_files"], ["new\nfile.txt"])
            git("add", "delete.txt")
            git("commit", "-m", "unexpected commit")
            result = evidence.change_summary(root, before, evidence.snapshot(root), [], "edit")
            self.assertTrue(result["head_changed"])
            self.assertIn("delete.txt", result["changed_files"])

    def test_scope_prefixes_and_invalid_paths(self):
        for path in ["/absolute", "../escape", "src/../escape", ".", "src/*", ".git/config"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                evidence.allowed_paths([path])
        before = {"available": True, "revision": "base", "files": {}}
        after = {**before, "files": {"src/a.py": "changed", "src-other/b.py": "changed"}}
        result = evidence.change_summary(Path.cwd(), before, after, ["src/"], "edit")
        self.assertEqual(result["scope_violations"], ["src-other/b.py"])
        self.assertFalse(evidence.change_summary(Path.cwd(), before, after, None, "edit")["scope_checked"])
        self.assertEqual(len(evidence.change_summary(Path.cwd(), before, after, None, "read")["scope_violations"]), 2)

    def test_cross_process_lock_and_release_on_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                      "from muse_evidence import job_lock; "
                      "\nwith job_lock(Path(sys.argv[2]), sys.argv[3]): pass")
            def attempt(workspace, session):
                return subprocess.run([sys.executable, "-c", script, str(SCRIPTS), str(workspace), session],
                                      capture_output=True).returncode
            with self.assertRaises(RuntimeError):
                with evidence.job_lock(root, "test-session-" + tmp):
                    self.assertNotEqual(attempt(root, "different"), 0)
                    self.assertNotEqual(attempt(root / "other", "test-session-" + tmp), 0)
                    raise RuntimeError("simulate failure")
            self.assertEqual(attempt(root, "different"), 0)

    def test_durable_usage_is_run_scoped_deduplicated_and_cache_conservative(self):
        def record(run, identifier, cache=0):
            return {"payload": {"kind": "run", "run_id": run, "source_run_record_id": identifier,
                "event": {"kind": "model_completed", "usage": {"input_tokens": 100,
                    "output_tokens": 20, "reasoning_tokens": 10, "cached_tokens": cache,
                    "cache_read_tokens": 0, "cache_write_tokens": 0}}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.json"
            records = [record("old", "old"), record("new", "one"), record("new", "one")]
            path.write_text(json.dumps({"events": records}))
            result = muse_worker.extract(path, "new")
            self.assertEqual(result["muse_usage"]["total_tokens"], 120)
            self.assertEqual(result["muse_usage"]["model_completions"], 1)
            self.assertIsNone(result["reasoning_effort"])
            records.append(record("new", "two", cache=50))
            path.write_text(json.dumps({"events": records}))
            result = muse_worker.extract(path, "new")
            self.assertEqual(result["muse_usage"]["input_tokens"], 200)
            self.assertIsNone(result["muse_usage"]["total_tokens"])


if __name__ == "__main__":
    unittest.main()
