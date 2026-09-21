#!/usr/bin/env python3
"""Run the installed Muse CLI and retain logs while emitting a compact result."""
import argparse
from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid


def parse_records(path):
    """Accept both Muse JSONL output and the offline export format."""
    with path.open(encoding="utf-8", errors="replace") as stream:
        first = next((line for line in stream if line.strip()), "")
        if first.strip() == "{":
            stream.seek(0)
            document = json.load(stream)
            for item in document.get("events", []):
                yield item.get("envelope", item)
            return
        stream.seek(0)
        for line in stream:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                if isinstance(item.get("events"), list):
                    for event in item["events"]:
                        yield event.get("envelope", event)
                else:
                    yield item.get("envelope", item)


def record_run_id(record):
    payload = record.get("payload", {})
    if not isinstance(payload, dict):
        return None
    stream = record.get("stream", {})
    return (payload.get("run_id") or payload.get("run_stream", {}).get("id") or
            (stream.get("id") if stream.get("kind") == "run" else None))


def latest_run_id(path):
    run_id = None
    for record in parse_records(path):
        payload = record.get("payload", {})
        if (record.get("payload_type") == "run.lifecycle.started" or
                (isinstance(payload, dict) and payload.get("kind") == "run")):
            run_id = record_run_id(record) or run_id
    return run_id


def extract(path, run_id=None):
    text, terminal, reason, model = "", None, None, None
    for record in parse_records(path):
        if run_id is not None and record_run_id(record) != run_id:
            continue
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if record.get("payload_type") == "run.model.configured":
            model = payload.get("record", payload).get("model_id") or model
        if payload.get("kind") == "run_terminal":
            terminal, reason = payload.get("terminal"), payload.get("reason")
            if payload.get("text", "").strip():
                text = payload["text"]
            continue
        event = payload.get("event", {})
        if payload.get("kind") != "run" or not isinstance(event, dict):
            continue
        if event.get("kind") == "assistant_message_committed" and event.get("text", "").strip():
            text = event["text"]
        elif event.get("kind") == "terminal":
            terminal = event.get("terminal")
            reason = event.get("reason")
    return {"answer": text, "terminal": terminal, "reason": reason, "model": model}


def linked_worktree(workspace):
    check = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--show-toplevel", "--git-dir", "--git-common-dir"],
        capture_output=True, text=True, check=False,
    )
    parts = check.stdout.splitlines()
    if check.returncode or len(parts) != 3:
        return False
    root, git_dir, common_dir = parts
    return (Path(root).resolve() == workspace and
            (workspace / git_dir).resolve() != (workspace / common_dir).resolve())


def compact(result, limit):
    answer = result.get("answer", "")
    result["answer_truncated"] = len(answer) > limit
    if result["answer_truncated"]:
        result["answer"] = answer[:limit] + "\n[Read result.txt for the complete answer.]"
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--mode", choices=["read", "edit"], help="New jobs default to read; resumes inherit")
    parser.add_argument("--resume", type=Path, help="Prior job directory with session.json; same workspace and mode only")
    parser.add_argument("--max-steps", type=int, default=24)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-output-chars", type=int, default=8000)
    parser.add_argument("--extract", type=Path, help="Recover an existing JSONL log or Muse export offline")
    args = parser.parse_args()
    if min(args.max_steps, args.timeout, args.max_output_chars) <= 0:
        parser.error("limits must be positive")
    if args.extract:
        if args.resume:
            parser.error("--extract is offline recovery; do not combine it with --resume")
        result = extract(args.extract, run_id=latest_run_id(args.extract))
        result["source"] = str(args.extract.resolve())
        if len(result["answer"]) > args.max_output_chars:
            result_path = Path(tempfile.mkdtemp(prefix="muse-result-")) / "result.txt"
            result_path.write_text(result["answer"], encoding="utf-8")
            result["result_file"] = str(result_path)
        compact(result, args.max_output_chars)
        return 0 if result["terminal"] == "completed" and result["answer"] else 1
    prior = None
    if args.resume:
        try:
            prior = json.loads((args.resume.expanduser() / "session.json").read_text(encoding="utf-8"))
            if (prior.get("schema") != 1 or prior.get("mode") not in ("read", "edit") or
                    not isinstance(prior.get("workspace"), str) or not Path(prior["workspace"]).is_absolute()):
                raise ValueError("invalid session metadata")
            prior["session_id"] = str(uuid.UUID(prior["session_id"]))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            parser.error(f"cannot resume this job: {exc}")
        previous_workspace = Path(prior["workspace"]).resolve()
        if args.workspace and args.workspace.expanduser().resolve() != previous_workspace:
            parser.error("resume cannot switch workspace; start a new job")
        if args.mode and args.mode != prior["mode"]:
            parser.error("resume cannot change read/edit mode; start a new job")
        args.workspace, args.mode = previous_workspace, prior["mode"]
    args.mode = args.mode or "read"
    if not args.workspace or not args.prompt_file:
        parser.error("--prompt-file and either --workspace or --resume are required")
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error("workspace must be an existing directory")
    if args.mode == "edit" and not linked_worktree(workspace):
        parser.error("edit mode requires the root of a linked Git worktree, not the primary checkout")
    muse = shutil.which("muse")
    if not muse:
        parser.error("muse CLI is not on PATH")
    prompt = args.prompt_file.expanduser().read_text(encoding="utf-8").strip()
    if not prompt:
        parser.error("prompt file is empty")
    run_dir = Path(tempfile.mkdtemp(prefix="codex-muse-"))
    session_id = prior["session_id"] if prior else str(uuid.uuid4())
    session_file = run_dir / "session.json"
    session_file.write_text(json.dumps({"schema": 1, "session_id": session_id,
                                       "workspace": str(workspace), "mode": args.mode}), encoding="utf-8")
    session_file.chmod(0o600)
    if prior:
        # Reusing an unknown ID can create a fresh session. Verify retained history
        # offline first, rather than silently losing the context we promised to reuse.
        resume_check = run_dir / "resume-check.json"
        try:
            checked = subprocess.run(
                [muse, "export", "--session", session_id, "--out", str(resume_check)],
                cwd=workspace, capture_output=True, text=True, timeout=20, check=False,
            )
            if checked.returncode:
                raise ValueError(checked.stderr[-1000:] or "session export failed")
            history = json.loads(resume_check.read_text(encoding="utf-8"))
            if not any(s.get("session_id") == session_id and s.get("turn_count", 0) > 0
                       for s in history.get("sessions", [])):
                raise ValueError("no retained turns for this session")
        except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
            parser.error(f"cannot resume retained session; no new model call made: {exc}")
    contract = (
        "You are a bounded worker for a supervising Codex agent. Execute only the assignment below. "
        "Do not delegate to other agents or start background tasks. Do not commit, push, deploy, "
        "send messages, change authentication/settings, or access unrelated secrets. "
        "You share the machine with other workers; preserve their changes and stay within assigned ownership. "
        "Report findings or changes, source paths/lines, checks and failures, and unresolved questions "
        "in at most 500 words. If blocked, stop and report the exact blocker.\n"
    )
    contract += ("Read only. Use read_file/search tools; shell execution and file writes are disabled.\n"
                 if args.mode == "read" else
                 "Edit only the assigned files in this isolated worktree and run relevant checks.\n")
    task_file = run_dir / "task.txt"
    task_file.write_text(contract + "\nAssignment:\n" + prompt + "\n", encoding="utf-8")
    command = [
        muse, "exec", "--json", "--workspace", str(workspace), "--worktree", "off",
        "--session-id", session_id, "--prompt-file", str(task_file),
        "--max-model-steps", str(args.max_steps), "--max-tool-output-bytes", "12000",
        "--no-foreign-personal-context", "--disable-web-tools", "--trust-workspace",
        "--approval-mode", "on-request", "--sandbox-network", "restricted",
    ]
    if args.mode == "read":
        command += ["--disable-write", "--disable-shell"]
    events_path, stderr_path = run_dir / "events.jsonl", run_dir / "stderr.log"
    print(f"Muse job {session_id}; logs: {run_dir}", file=sys.stderr, flush=True)
    interruption = None
    with events_path.open("w") as events, stderr_path.open("w") as errors:
        process = subprocess.Popen(command, cwd=workspace, stdin=subprocess.DEVNULL,
                                   stdout=events, stderr=errors, start_new_session=True)
        try:
            code = process.wait(timeout=args.timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            interruption = "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "interrupted"
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code = 124 if interruption == "timeout" else 130
    run_id = latest_run_id(events_path)
    result = extract(events_path, run_id=run_id)
    # Export is offline. Recover from CLI event format differences without another model call.
    # A resumed export includes older successful turns. Without this turn's ID,
    # never mistake an earlier answer for a successful follow-up.
    if (not result["answer"] or not result["terminal"]) and (run_id or not prior):
        export_path = run_dir / "export.json"
        with stderr_path.open("a") as errors:
            try:
                exported = subprocess.run(
                    [muse, "export", "--session", session_id, "--out", str(export_path)],
                    cwd=workspace, stdout=errors, stderr=errors, timeout=20, check=False,
                )
                if exported.returncode == 0:
                    result = extract(export_path, run_id=run_id)
            except subprocess.TimeoutExpired:
                pass
    result_path = run_dir / "result.txt"
    result_path.write_text(result["answer"], encoding="utf-8")
    success = code == 0 and result["terminal"] == "completed" and bool(result["answer"])
    result.update({"status": "completed" if success else "failed", "exit_code": code,
                   "session_id": session_id, "workspace": str(workspace), "mode": args.mode,
                   "logs": str(run_dir), "result_file": str(result_path),
                   "resumed": prior is not None})
    if interruption:
        result["reason"] = interruption
    if not success:
        result["stderr_tail"] = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        result["reason"] = result["reason"] or "Missing successful completion; inspect retained logs."
    compact(result, args.max_output_chars)
    return 0 if success else (code if code > 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
