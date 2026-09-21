"""Portable offline tests for muse_worker and context_filter helpers.

Standard library only. No network or model calls.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

_HERE = Path(__file__).parent
_MUSE_REL = Path("../skills/muse-delegate/scripts/muse_worker.py")
_JEV_REL = Path("../skills/jev-context/scripts/context_filter.py")


def _load(name, rel):
    path = (_HERE / rel).resolve()
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


muse_worker = _load("muse_worker", _MUSE_REL)
context_filter = _load("context_filter", _JEV_REL)


def _muse_records(answer="hello answer", terminal="completed", reason="done",
                   model="m-1", extra=()):
    records = [
        {"payload_type": "run.model.configured",
         "payload": {"record": {"model_id": model}}},
        {"payload": {"kind": "run",
                     "event": {"kind": "assistant_message_committed",
                               "text": answer}}},
        {"payload": {"kind": "run",
                     "event": {"kind": "terminal", "terminal": terminal,
                               "reason": reason}}},
    ]
    records.extend(extra)
    return records


def _write_live_jsonl(path, records, envelope=False, garbage=False):
    with path.open("w", encoding="utf-8") as handle:
        for index, record in enumerate(records):
            item = {"envelope": record} if envelope else record
            handle.write(json.dumps(item) + "\n")
            if garbage and index == 0:
                handle.write("not json at all\n")


def _write_compact_export(path, records, envelope=True):
    events = [{"envelope": r} if envelope else r for r in records]
    path.write_text(json.dumps({"events": events}), encoding="utf-8")


def _write_pretty_export(path, records, envelope=True):
    events = [{"envelope": r} if envelope else r for r in records]
    path.write_text(json.dumps({"events": events}, indent=2) + "\n",
                    encoding="utf-8")


def _run_muse_extract(path, max_chars=8000):
    argv = ["muse_worker.py", "--extract", str(path),
           "--max-output-chars", str(max_chars)]
    stdout = io.StringIO()
    with mock.patch.object(sys, "argv", argv):
        with contextlib.redirect_stdout(stdout):
            code = muse_worker.main()
    return code, json.loads(stdout.getvalue())


def _git_available():
    return shutil.which("git") is not None


def _run_git(args, cwd, hooks_dir):
    base = ["git", "-c", "user.name=Test User",
            "-c", "user.email=test@example.com",
            "-c", "core.hooksPath=" + str(hooks_dir),
            "-c", "init.defaultBranch=main",
            "-c", "protocol.file.allow=always"]
    return subprocess.run(base + args, cwd=str(cwd), capture_output=True,
                          text=True, timeout=30)


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        network = mock.patch('socket.create_connection', side_effect=AssertionError('Tests must not access the network'))
        network.start()
        self.addCleanup(network.stop)


class TestMuseWorkerExtract(OfflineTestCase):
    def test_live_jsonl_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, _muse_records())
            result = muse_worker.extract(path)
        self.assertEqual(result["answer"], "hello answer")
        self.assertEqual(result["terminal"], "completed")
        self.assertEqual(result["reason"], "done")
        self.assertEqual(result["model"], "m-1")

    def test_pretty_export_matches_live(self):
        records = _muse_records()
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live.jsonl"
            pretty = Path(tmp) / "pretty.json"
            _write_live_jsonl(live, records)
            _write_pretty_export(pretty, records)
            self.assertEqual(muse_worker.extract(pretty),
                             muse_worker.extract(live))

    def test_compact_export_matches_live(self):
        records = _muse_records()
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live.jsonl"
            compact = Path(tmp) / "compact.json"
            _write_live_jsonl(live, records)
            _write_compact_export(compact, records)
            self.assertEqual(muse_worker.extract(compact),
                             muse_worker.extract(live))

    def test_envelope_and_bare_forms_match(self):
        records = _muse_records()
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bare.jsonl"
            wrapped = Path(tmp) / "wrapped.jsonl"
            _write_live_jsonl(bare, records, envelope=False)
            _write_live_jsonl(wrapped, records, envelope=True)
            self.assertEqual(muse_worker.extract(bare),
                             muse_worker.extract(wrapped))

    def test_malformed_lines_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, _muse_records(), garbage=True)
            result = muse_worker.extract(path)
        self.assertEqual(result["answer"], "hello answer")
        self.assertEqual(result["terminal"], "completed")

    def test_empty_assistant_message_does_not_erase(self):
        records = [
            {"payload": {"kind": "run", "event": {
                "kind": "assistant_message_committed",
                "text": "first answer"}}},
            {"payload": {"kind": "run", "event": {
                "kind": "assistant_message_committed", "text": "   "}}},
            {"payload": {"kind": "run", "event": {
                "kind": "assistant_message_committed", "text": ""}}},
            {"payload": {"kind": "run", "event": {
                "kind": "terminal", "terminal": "completed",
                "reason": "done"}}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, records)
            result = muse_worker.extract(path)
        self.assertEqual(result["answer"], "first answer")
        self.assertEqual(result["terminal"], "completed")

    def test_empty_run_terminal_text_does_not_erase(self):
        records = [
            {"payload": {"kind": "run", "event": {
                "kind": "assistant_message_committed",
                "text": "keep me"}}},
            {"payload": {"kind": "run_terminal", "terminal": "completed",
                         "reason": "ok", "text": "  "}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, records)
            result = muse_worker.extract(path)
        self.assertEqual(result["answer"], "keep me")
        self.assertEqual(result["terminal"], "completed")

    def test_nonempty_run_terminal_text_updates(self):
        records = [
            {"payload": {"kind": "run", "event": {
                "kind": "assistant_message_committed", "text": "first"}}},
            {"payload": {"kind": "run_terminal", "terminal": "completed",
                         "reason": "ok", "text": "final"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, records)
            result = muse_worker.extract(path)
        self.assertEqual(result["answer"], "final")

    def test_completed_extract_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, _muse_records())
            code, result = _run_muse_extract(path)
        self.assertEqual(code, 0)
        self.assertEqual(result["answer"], "hello answer")
        self.assertEqual(result["terminal"], "completed")
        self.assertFalse(result["answer_truncated"])

    def test_incomplete_extract_exit_nonzero(self):
        records = [
            {"payload": {"kind": "run", "event": {
                "kind": "assistant_message_committed",
                "text": "partial without terminal"}}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, records)
            code, result = _run_muse_extract(path)
        self.assertEqual(code, 1)
        self.assertEqual(result["answer"], "partial without terminal")
        self.assertIsNone(result["terminal"])

    def test_failed_terminal_extract_exit_nonzero(self):
        records = _muse_records(answer="tried", terminal="failed",
                                reason="tool error")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, records)
            code, result = _run_muse_extract(path)
        self.assertEqual(code, 1)
        self.assertEqual(result["terminal"], "failed")

    def test_empty_answer_extract_exit_nonzero(self):
        records = [
            {"payload": {"kind": "run", "event": {
                "kind": "terminal", "terminal": "completed",
                "reason": "done"}}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, records)
            code, result = _run_muse_extract(path)
        self.assertEqual(code, 1)
        self.assertEqual(result["answer"], "")

    def test_extract_truncates_long_answer(self):
        records = _muse_records(answer="x" * 2000)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            _write_live_jsonl(path, records)
            code, result = _run_muse_extract(path, max_chars=1000)
        self.assertEqual(code, 0)
        self.assertTrue(result["answer_truncated"])
        self.assertIn("result_file", result)
        full = Path(result["result_file"]).read_text(encoding="utf-8")
        self.assertEqual(full, "x" * 2000)
        self.addCleanup(shutil.rmtree, Path(result['result_file']).parent)


class TestMuseResume(OfflineTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("Synthetic bounded follow-up")
        self.real_mkdtemp = tempfile.mkdtemp

    def invoke(self, arguments, records, history=True, exported_records=(), wait_error=None):
        def export(command, **kwargs):
            path = Path(command[command.index("--out") + 1])
            session = command[command.index("--session") + 1]
            path.write_text(json.dumps({
                "sessions": [{"session_id": session, "turn_count": 1}] if history else [],
                "events": list(exported_records),
            }))
            return subprocess.CompletedProcess(command, 0, "", "")

        def launch(command, **kwargs):
            for record in records:
                kwargs["stdout"].write(json.dumps(record) + "\n")
            process = mock.Mock()
            if wait_error:
                process.wait.side_effect = [wait_error, 0]
            else:
                process.wait.return_value = 0
            return process

        output = io.StringIO()
        with (mock.patch.object(sys, "argv", ["muse_worker.py", "--prompt-file", str(self.prompt), *arguments]),
              mock.patch.object(muse_worker.shutil, "which", return_value="muse"),
              mock.patch.object(muse_worker.tempfile, "mkdtemp", side_effect=lambda **kw: self.real_mkdtemp(dir=self.root, **kw)),
              mock.patch.object(muse_worker.subprocess, "run", side_effect=export),
              mock.patch.object(muse_worker.subprocess, "Popen", side_effect=launch) as popen,
              mock.patch.object(muse_worker.os, "killpg"),
              contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO())):
            try:
                code = muse_worker.main()
            except SystemExit as exc:
                return exc.code, None, popen.call_args_list
        return code, json.loads(output.getvalue()), popen.call_args_list

    def first_job(self):
        code, result, _ = self.invoke(["--workspace", str(self.root)], _muse_records())
        self.assertEqual(code, 0)
        return result

    def test_followup_reuses_identity_and_preserves_read_boundary_and_logs(self):
        first = self.first_job()
        original = (Path(first["logs"]) / "events.jsonl").read_bytes()
        code, second, calls = self.invoke(["--resume", first["logs"]], _muse_records(answer="follow-up"))
        self.assertEqual(code, 0)
        self.assertTrue(second["resumed"])
        self.assertEqual(second["session_id"], first["session_id"])
        self.assertEqual(second["workspace"], first["workspace"])
        self.assertNotEqual(second["logs"], first["logs"])
        self.assertEqual(second["answer"], "follow-up")
        command = calls[0].args[0]
        self.assertEqual(command[command.index("--session-id") + 1], first["session_id"])
        self.assertIn("--disable-write", command)
        self.assertIn("--disable-shell", command)
        self.assertEqual((Path(first["logs"]) / "events.jsonl").read_bytes(), original)

    def test_overrides_handoff_and_ledger_separate_acceptance(self):
        ledger = self.root / "task.ledger.jsonl"
        code, result, calls = self.invoke(["--workspace", str(self.root), "--task-id", "example",
            "--model", "m-1", "--reasoning-effort", "max", "--allow-path", "src/", "--ledger", str(ledger)],
            _muse_records())
        self.assertEqual(code, 0)
        command = calls[0].args[0]
        self.assertEqual(command[command.index("--reasoning-effort") + 1], "max")
        self.assertEqual(command[command.index("--model") + 1], "m-1")
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["acceptance_status"], "unreviewed")
        self.assertIsNone(result["configuration"]["matches_requested"])
        self.assertIsNone(result["configuration"]["observed"]["reasoning_effort"])
        self.assertTrue(result["ledger_recorded"])
        self.assertEqual(json.loads(Path(result["handoff_file"]).read_text())["attempt_id"], result["attempt_id"])
        code, second, calls = self.invoke(["--resume", result["logs"]], _muse_records())
        self.assertEqual(second["task_id"], "example")
        self.assertEqual(second["changes"]["allowed_paths"], ["src/"])
        self.assertNotIn("--model", calls[0].args[0])
        self.assertNotIn("--reasoning-effort", calls[0].args[0])

    def test_timeout_records_failed_execution_not_old_completion(self):
        code, result, _ = self.invoke(["--workspace", str(self.root)], _muse_records(),
                                      wait_error=subprocess.TimeoutExpired("muse", 1))
        self.assertEqual(code, 124)
        self.assertEqual(result["execution_status"], "failed")
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["acceptance_status"], "unreviewed")
        # Lock must have released after the failed attempt.
        self.assertEqual(self.first_job()["execution_status"], "completed")

    def test_resume_rejects_workspace_mode_and_missing_metadata_before_launch(self):
        first = self.first_job()
        for extra in (["--workspace", str(self.root / "elsewhere")], ["--mode", "edit"]):
            with self.subTest(extra=extra):
                code, _, calls = self.invoke(["--resume", first["logs"], *extra], [])
                self.assertEqual(code, 2)
                self.assertFalse(calls)
        code, _, calls = self.invoke(["--resume", str(self.root / "missing")], [])
        self.assertEqual(code, 2)
        self.assertFalse(calls)

    def test_missing_retained_history_does_not_silently_start_over(self):
        first = self.first_job()
        code, _, calls = self.invoke(["--resume", first["logs"]], [], history=False)
        self.assertEqual(code, 2)
        self.assertFalse(calls)

    def test_failed_followup_export_cannot_reuse_previous_success(self):
        first = self.first_job()
        records = _muse_records(answer="old success")
        for record in records:
            record["payload"]["run_id"] = "old-run"
        records.append({"payload": {"kind": "run", "run_id": "new-run", "event": {
            "kind": "terminal", "terminal": "failed", "reason": "synthetic failure"}}})
        live = [{"payload_type": "run.lifecycle.started", "payload": {
            "kind": "run_started", "run_stream": {"kind": "run", "id": "new-run"}}}]
        code, result, _ = self.invoke(["--resume", first["logs"]], live, exported_records=records)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["answer"], "")
        self.assertEqual(result["reason"], "synthetic failure")


class TestMuseWorktree(OfflineTestCase):
    def test_non_git_directory_is_not_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(
                muse_worker.linked_worktree(Path(tmp).resolve()))

    @unittest.skipUnless(_git_available(), "git is required")
    def test_primary_checkout_is_not_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            hooks = Path(tmp) / "hooks"
            hooks.mkdir()
            proc = _run_git(["init"], root, hooks)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            (root / "note.txt").write_text("hello\n", encoding="utf-8")
            self.assertEqual(_run_git(["add", "note.txt"], root, hooks).returncode, 0)
            commit = _run_git(["commit", "-m", "init", "--no-gpg-sign"],
                              root, hooks)
            self.assertEqual(commit.returncode, 0, commit.stderr)
            self.assertFalse(
                muse_worker.linked_worktree(root.resolve()))

    @unittest.skipUnless(_git_available(), "git is required")
    def test_linked_worktree_is_recognized(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "repo"
            root.mkdir()
            hooks = tmp_path / "hooks"
            hooks.mkdir()
            self.assertEqual(_run_git(["init"], root, hooks).returncode, 0)
            (root / "note.txt").write_text("hello\n", encoding="utf-8")
            self.assertEqual(_run_git(["add", "note.txt"], root, hooks).returncode, 0)
            commit = _run_git(["commit", "-m", "init", "--no-gpg-sign"],
                              root, hooks)
            self.assertEqual(commit.returncode, 0, commit.stderr)
            linked = tmp_path / "linked"
            added = _run_git(["worktree", "add", "--detach", str(linked)],
                             root, hooks)
            self.assertEqual(added.returncode, 0, added.stderr)
            try:
                self.assertFalse(
                    muse_worker.linked_worktree(root.resolve()))
                self.assertTrue(
                    muse_worker.linked_worktree(linked.resolve()))
            finally:
                _run_git(["worktree", "remove", "--force", str(linked)],
                         root, hooks)


def _write_tree(root, files):
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _run_filter(argv):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = context_filter.main(argv)
    text = stdout.getvalue()
    return code, text, json.loads(text)


def _valid_answer(choice="relevant"):
    probs = {"relevant": 0.7, "irrelevant": 0.1, "uncertain": 0.2}
    return {"type": "choice", "choice": choice, "confidence": 0.8,
            "probabilities": probs}


class TestContextFilterLocal(OfflineTestCase):
    def test_local_bounded_output_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "root"
            root.mkdir()
            _write_tree(root, {
                "alpha.py": "def alpha():\n    return 'payment retry'\n",
                "beta.py": "def beta():\n    return 'unrelated garden'\n",
            })
            manifest = tmp_path / "out" / "index.json"
            cache = tmp_path / "cache"
            budget = 6000
            code, text, result = _run_filter([
                "alpha.py", "beta.py", "--query", "payment retry logic",
                "--root", str(root), "--backend", "local",
                "--manifest", str(manifest), "--cache-dir", str(cache),
                "--budget-chars", str(budget)])
            self.assertEqual(code, 0)
            self.assertEqual(result["backend"], "local")
            self.assertTrue(result["excerpts"])
            self.assertLessEqual(result["metrics"]["output_chars"], budget)
            self.assertLessEqual(len(text), budget + 1)
            self.assertTrue(manifest.is_file())
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(manifest_data["root"], str(root.resolve()))
            self.assertEqual(manifest_data["query"], "payment retry logic")
            self.assertEqual(manifest_data["metrics"]["candidate_chunks"],
                             len(manifest_data["chunks"]))
            by_id = {item["id"]: item for item in result["excerpts"]}
            for chunk in manifest_data["chunks"]:
                self.assertNotIn("text", chunk)
                self.assertIn("sha256", chunk)
                if chunk["selected"]:
                    self.assertIn(chunk["id"], by_id)
                    expected = hashlib.sha256(
                        by_id[chunk["id"]]["text"].encode()).hexdigest()
                    self.assertEqual(chunk["sha256"], expected)
                for key in ("path", "start_line", "end_line"):
                    self.assertIn(key, chunk)
            self.assertEqual(
                manifest_data["metrics"]["selected_chunks"],
                len(result["excerpts"]))

    def test_small_budget_stays_bounded_and_marks_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "root"
            root.mkdir()
            files = {f"mod{i}.py": ("value = %d\n# payment retry\n" % i) * 40
                     for i in range(6)}
            _write_tree(root, files)
            manifest = tmp_path / "index.json"
            code, text, result = _run_filter(
                list(files) + ["--query", "payment retry",
                               "--root", str(root), "--backend", "local",
                               "--manifest", str(manifest),
                               "--cache-dir", str(tmp_path / "cache"),
                               "--budget-chars", "2000"])
            self.assertEqual(code, 0)
            self.assertLessEqual(result["metrics"]["output_chars"], 2000)
            self.assertTrue(result["metrics"]["incomplete"])

    def test_path_outside_root_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "root"
            root.mkdir()
            (root / "good.txt").write_text("payment retry notes\n",
                                           encoding="utf-8")
            outside = tmp_path / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")
            chunks, skipped, _ = context_filter.read_candidates(
                root.resolve(), ["../outside.txt", "good.txt"],
                "payment retry")
            reasons = {item["path"]: item["reason"] for item in skipped}
            self.assertEqual(reasons.get("../outside.txt"), "outside_root")
            self.assertTrue(all(chunk["path"] == "good.txt"
                                for chunk in chunks))
            self.assertTrue(chunks)

    def test_credential_paths_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "root"
            root.mkdir()
            _write_tree(root, {
                "notes.txt": "payment retry notes\n",
                "credentials.json": '{"token": "abc"}\n',
                ".env": "KEY=value\n",
                "keys/secret.pem": "pem body\n",
            })
            chunks, skipped, _ = context_filter.read_candidates(
                root.resolve(),
                ["notes.txt", "credentials.json", ".env",
                 "keys/secret.pem"],
                "payment retry")
            reasons = {item["path"]: item["reason"] for item in skipped}
            self.assertEqual(reasons.get("credentials.json"),
                             "credential_path")
            self.assertEqual(reasons.get(".env"), "credential_path")
            self.assertEqual(reasons.get(str(Path("keys/secret.pem"))),
                             "credential_path")
            self.assertTrue(chunks)
            self.assertTrue(all(chunk["path"] == "notes.txt"
                                for chunk in chunks))

    def test_missing_key_falls_back_to_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "root"
            root.mkdir()
            (root / "a.txt").write_text("payment retry\n", encoding="utf-8")
            manifest = tmp_path / "index.json"
            env = {key: "" for key in
                   ("TYPESAFE_API_KEY", "JEV_API_KEY",
                    "TYPESAFE_API_KEY_FILE") if key in os.environ}
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(context_filter, 'key_value', return_value=None):
                for key in ("TYPESAFE_API_KEY", "JEV_API_KEY",
                            "TYPESAFE_API_KEY_FILE"):
                    os.environ.pop(key, None)
                code, _, result = _run_filter([
                    "a.txt", "--query", "payment retry",
                    "--root", str(root), "--backend", "jev",
                    "--manifest", str(manifest),
                    "--cache-dir", str(tmp_path / "cache")])
            self.assertEqual(code, 0)
            self.assertEqual(result["backend"], "local")
            self.assertEqual(result["metrics"].get("fallback"),
                             "missing_key")
            self.assertTrue(result["excerpts"])

    def test_mocked_api_failure_keeps_local_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "root"
            root.mkdir()
            (root / "a.txt").write_text("payment retry\n", encoding="utf-8")
            manifest = tmp_path / "index.json"
            with mock.patch.object(context_filter.request, 'build_opener') as opener, mock.patch.object(context_filter, 'key_value', return_value='synthetic-test-key'):
                opener.return_value.open.side_effect = URLError('offline fixture')
                with mock.patch.dict(os.environ,
                                     {"TYPESAFE_API_KEY": "synthetic-test-key"}):
                    code, _, result = _run_filter([
                        "a.txt", "--query", "payment retry",
                        "--root", str(root), "--backend", "jev",
                        "--manifest", str(manifest),
                        "--cache-dir", str(tmp_path / "cache")])
            self.assertEqual(code, 0)
            self.assertEqual(result["backend"], "local")
            self.assertEqual(
                result["metrics"].get("fallback"),
                "unscored_candidates_use_local_ranking")
            self.assertIn("jev_connection_error",
                          result["metrics"]["jev"]["errors"])
            self.assertTrue(result["excerpts"])

    def test_rank_caches_success_and_reuses_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "root"
            root.mkdir()
            (root / "a.txt").write_text("payment retry alpha\n",
                                        encoding="utf-8")
            cache = tmp_path / "cache"
            chunks, _, _ = context_filter.read_candidates(
                root.resolve(), ["a.txt"], "payment retry")

            def fake(payload, key):
                self.assertEqual(key, "synthetic-test-key")
                answers = {chunk_id: _valid_answer()
                           for chunk_id in payload["questions"]}
                return {"model": context_filter.MODEL, "answers": answers,
                        "usage": {"input_tokens": 7}}

            caller = mock.Mock(side_effect=fake)
            info = context_filter.rank_jev(chunks, "payment retry",
                                           "synthetic-test-key", cache, 10,
                                           caller=caller)
            self.assertGreater(info["scored"], 0)
            self.assertEqual(info["errors"], [])
            self.assertEqual(caller.call_count, 1)
            self.assertEqual(info["input_tokens"], 7)
            self.assertTrue(any(cache.iterdir()))

            failing = mock.Mock(side_effect=ValueError("jev_http_500"))
            chunks2, _, _ = context_filter.read_candidates(
                root.resolve(), ["a.txt"], "payment retry")
            info2 = context_filter.rank_jev(chunks2, "payment retry",
                                            "synthetic-test-key", cache, 10,
                                            caller=failing)
            self.assertEqual(failing.call_count, 0)
            self.assertGreater(info2["cache_hits"], 0)
            self.assertGreater(info2["scored"], 0)

    def test_rank_invalid_response_records_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "root"
            root.mkdir()
            (root / "a.txt").write_text("payment retry\n", encoding="utf-8")
            chunks, _, _ = context_filter.read_candidates(
                root.resolve(), ["a.txt"], "payment retry")

            def bad(payload, key):
                return {"model": context_filter.MODEL, "answers": {}}

            info = context_filter.rank_jev(chunks, "payment retry", "k",
                                           tmp_path / "cache", 10,
                                           caller=bad)
            self.assertEqual(info["scored"], 0)
            self.assertTrue(info["errors"])
            self.assertNotIn("jev", chunks[0])


if __name__ == "__main__":
    unittest.main()
