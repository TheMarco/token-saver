#!/usr/bin/env python3
"""Run the installed Muse CLI and retain logs while emitting a compact result."""
import argparse
from contextlib import suppress, ExitStack
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from muse_evidence import job_lock, allowed_paths, snapshot, change_summary, configuration
from task_ledger import append_event


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
    if payload.get("kind") == "run_model":
        return payload.get("record", {}).get("run_stream", {}).get("id")
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
    effort, cli_version = None, None
    usages, seen = [], set()
    for record in parse_records(path):
        payload = record.get("payload", {})
        if isinstance(payload, dict) and payload.get("kind") == "metadata":
            cli_version = payload.get("record", {}).get("build", {}).get("semver") or cli_version
        if run_id is not None and record_run_id(record) != run_id:
            continue
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if record.get("payload_type") == "run.model.configured" or payload.get("kind") == "run_model":
            settings = payload.get("record", payload)
            model = settings.get("model_id") or model
            effort = settings.get("reasoning_effort") or effort
        if payload.get("kind") == "run_terminal":
            terminal, reason = payload.get("terminal"), payload.get("reason")
            if payload.get("text", "").strip():
                text = payload["text"]
            continue
        event = payload.get("event", {})
        if payload.get("kind") != "run" or not isinstance(event, dict):
            continue
        if event.get("kind") == "model_completed":
            identity = payload.get("source_run_record_id") or record.get("id")
            if identity is None or identity not in seen:
                usages.append(event.get("usage") or {})
                if identity is not None:
                    seen.add(identity)
        if event.get("kind") == "assistant_message_committed" and event.get("text", "").strip():
            text = event["text"]
        elif event.get("kind") == "terminal":
            terminal = event.get("terminal")
            reason = event.get("reason")
    def total(key):
        values = [u.get(key) for u in usages]
        return (sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None)
    # Raw provider input counters have provider-specific cache conventions. Only
    # derive a total when every completion explicitly reports zero cache counters.
    uncached = bool(usages) and all(all(type(u.get(k)) is int and u[k] == 0 for k in
        ("cached_tokens", "cache_read_tokens", "cache_write_tokens")) for u in usages)
    input_tokens, output_tokens = total("input_tokens"), total("output_tokens")
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
             "total_tokens": input_tokens + output_tokens if uncached and input_tokens is not None and output_tokens is not None else None,
             "reasoning_tokens": total("reasoning_tokens"), "model_completions": len(usages),
             "coverage": "reported_foreground_completions_only" if usages else "unavailable",
             "includes_background_agents": False}
    return {"answer": text, "terminal": terminal, "reason": reason, "model": model,
            "reasoning_effort": effort, "cli_version": None,
            "session_build_version": cli_version, "muse_usage": usage}


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
    """Bound the entire stdout JSON, including its newline, without losing evidence."""
    if limit < 3:
        raise ValueError("output limit must be at least 3 characters for JSON and newline")
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    full = {**result, "answer_truncated": False, "output_truncated": False}
    if len(encode(full)) <= limit:
        sys.stdout.write(encode(full))
        return
    handoff = result.get("handoff_file")
    if not handoff or not Path(handoff).is_file():
        handoff = str(Path(tempfile.mkdtemp(prefix="muse-result-")) / "handoff.json")
        full["handoff_file"] = handoff
        Path(handoff).write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        Path(handoff).chmod(0o600)
    answer = result.get("answer", "")
    displayed = {}
    def include(key, value):
        candidate = {**displayed, key: value}
        if len(encode(candidate)) <= limit:
            displayed[key] = value
    include("answer_truncated", bool(answer))
    include("handoff_file", handoff)
    include("output_truncated", True)
    for key in ("execution_status", "acceptance_status", "status", "terminal", "exit_code",
                "review_flags", "ledger_error", "reason", "result_file"):
        if key in result:
            include(key, result[key])
    changes = result.get("changes", {})
    include("change_counts", {key: len(value) for key, value in changes.items() if isinstance(value, list)})
    # JSON escaping matters: slicing the rendered JSON would make it invalid.
    low, high = 0, len(answer)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = {**displayed, "answer": answer[:mid], "answer_truncated": mid < len(answer)}
        if len(encode(candidate)) <= limit:
            low = mid
        else:
            high = mid - 1
    if low:
        displayed.update(answer=answer[:low], answer_truncated=low < len(answer))
    if "handoff_file" not in displayed:
        print(f"Full result: {handoff}", file=sys.stderr)
    sys.stdout.write(encode(displayed))


class WorkerTerminated(BaseException):
    pass


def stop_worker(process):
    """Keep locks held until the worker is reaped; kill remaining group members too."""
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
        reaped = True
    except subprocess.TimeoutExpired:
        reaped = False
    # The group leader may exit while descendants ignore TERM.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    if not reaped:
        process.wait()


def run(locks, termination):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--mode", choices=["read", "edit"], help="New jobs default to read; resumes inherit")
    parser.add_argument("--resume", type=Path, help="Prior job directory with session.json; same workspace and mode only")
    parser.add_argument("--max-steps", type=int, default=24)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-output-chars", type=int, default=3000, help="Entire stdout JSON budget, including newline (default 3000, minimum 3); full evidence stays on disk")
    parser.add_argument("--extract", type=Path, help="Recover an existing JSONL log or Muse export offline")
    parser.add_argument("--model", help="Per-turn model override; does not change defaults")
    parser.add_argument("--reasoning-effort", choices=["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"])
    parser.add_argument("--allow-path", action="append", help="Repeatable repository-relative file or directory ending in /; resumes inherit")
    parser.add_argument("--task-id", help="Stable assignment ID for grouping follow-ups in a local ledger")
    parser.add_argument("--ledger", type=Path, help="Optional local JSONL evidence ledger (no uploads)")
    args = parser.parse_args()
    if min(args.max_steps, args.timeout, args.max_output_chars) <= 0:
        parser.error("limits must be positive")
    if args.max_output_chars < 3:
        parser.error("--max-output-chars must be at least 3")
    try:
        args.allow_path = allowed_paths(args.allow_path)
    except ValueError as exc:
        parser.error(str(exc))
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
    try:
        locks.enter_context(job_lock(workspace, session_id))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    started = time.monotonic()
    before = snapshot(workspace)
    task_id = args.task_id or (prior or {}).get("task_id") or session_id
    if prior and prior.get("task_id") and args.task_id and args.task_id != prior["task_id"]:
        parser.error("resume cannot change task ID; start a new assignment")
    scope = args.allow_path if args.allow_path is not None else (prior or {}).get("allowed_paths")
    try:
        scope = allowed_paths(scope)
    except ValueError as exc:
        parser.error(str(exc))
    attempt_id = str(uuid.uuid4())
    session_file = run_dir / "session.json"
    session_file.write_text(json.dumps({"schema": 1, "session_id": session_id,
                                       "workspace": str(workspace), "mode": args.mode,
                                       "task_id": task_id, "allowed_paths": scope}), encoding="utf-8")
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
        "in at most 150 words, with references to details instead of transcripts. "
        "Start with the assigned focused check; expand only for a concrete failure, affected dependency, "
        "risk, or required gate, and explain why. If blocked, stop and report the exact blocker.\n"
    )
    contract += ("Read only. Use read_file/search tools; shell execution and file writes are disabled.\n"
                 if args.mode == "read" else
                 "Edit only the assigned files in this isolated worktree and run relevant checks.\n")
    if scope is not None:
        contract += "Allowed repository-relative paths: " + json.dumps(scope) + ". No other edits.\n"
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
    if args.model is not None:
        command += ["--model", args.model]
    if args.reasoning_effort is not None:
        command += ["--reasoning-effort", args.reasoning_effort]
    events_path, stderr_path = run_dir / "events.jsonl", run_dir / "stderr.log"
    print(f"Muse job {session_id}; logs: {run_dir}", file=sys.stderr, flush=True)
    interruption = None
    with events_path.open("w") as events, stderr_path.open("w") as errors:
        if termination["signal"]:
            return 128 + termination["signal"]
        try:
            process = subprocess.Popen(command, cwd=workspace, stdin=subprocess.DEVNULL,
                                       stdout=events, stderr=errors, start_new_session=True)
        except OSError as exc:
            errors.write(str(exc))
            code, interruption = 127, "launch_failed"
        else:
            try:
                try:
                    # During launch/cleanup the handler only records the signal,
                    # preventing a spawn race or repeated signals skipping cleanup.
                    termination["waiting"] = True
                    if termination["signal"]:
                        raise WorkerTerminated()
                    code = process.wait(timeout=args.timeout)
                finally:
                    termination["waiting"] = False
            except (subprocess.TimeoutExpired, KeyboardInterrupt, WorkerTerminated) as exc:
                interruption = "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "interrupted"
                stop_worker(process)
                code = 124 if interruption == "timeout" else 128 + (termination["signal"] or signal.SIGINT)
    run_id = latest_run_id(events_path)
    result = extract(events_path, run_id=run_id)
    # Export is offline. Recover from CLI event format differences without another model call.
    # A resumed export includes older successful turns. Without this turn's ID,
    # never mistake an earlier answer for a successful follow-up.
    # The offline durable export also contains usage absent from the live stream.
    if run_id or not prior:
        export_path = run_dir / "export.json"
        with stderr_path.open("a") as errors:
            try:
                exported = subprocess.run(
                    [muse, "export", "--session", session_id, "--out", str(export_path)],
                    cwd=workspace, stdout=errors, stderr=errors, timeout=20, check=False,
                )
                if exported.returncode == 0:
                    recovered = extract(export_path, run_id=run_id)
                    for key, value in recovered.items():
                        if value is not None and value != "" and (key != "muse_usage" or value["model_completions"]):
                            result[key] = value
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
    result_path = run_dir / "result.txt"
    result_path.write_text(result["answer"], encoding="utf-8")
    success = code == 0 and result["terminal"] == "completed" and bool(result["answer"])
    result.update({"status": "completed" if success else "failed", "exit_code": code,
                   "execution_status": "completed" if success else "failed",
                   "acceptance_status": "unreviewed", "checks": None,
                   "task_id": task_id, "attempt_id": attempt_id,
                   "session_id": session_id, "workspace": str(workspace), "mode": args.mode,
                   "logs": str(run_dir), "result_file": str(result_path),
                   "resumed": prior is not None})
    # Export metadata describes the session's original build, not necessarily the
    # binary running a later resumed turn. Keep these measurements separate.
    try:
        version = subprocess.run([muse, "--version"], capture_output=True, text=True, timeout=10, check=False)
        result["cli_version"] = version.stdout.strip() if version.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        result["cli_version"] = None
    result["configuration"] = configuration({"model": args.model, "reasoning_effort": args.reasoning_effort}, result)
    result["changes"] = change_summary(workspace, before, snapshot(workspace), scope, args.mode)
    result["review_flags"] = []
    if result["changes"]["scope_violations"]:
        result["review_flags"].append("out_of_scope_changes")
    if result["changes"].get("head_changed"):
        result["review_flags"].append("unexpected_commit_or_checkout")
    if not result["changes"]["scope_checked"]:
        result["review_flags"].append("scope_not_verified")
    if result["configuration"]["matches_requested"] is False:
        result["review_flags"].append("configuration_mismatch")
    if interruption:
        result["reason"] = interruption
    if not success:
        result["stderr_tail"] = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        result["reason"] = result["reason"] or "Missing successful completion; inspect retained logs."
    handoff = run_dir / "handoff.json"
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["handoff_file"] = str(handoff)
    result["ledger_recorded"] = False
    if args.ledger:
        try:
            append_event(args.ledger.expanduser().absolute(), {
                "type": "execution", "task_id": task_id, "attempt_id": attempt_id,
                "execution_status": result["execution_status"], "elapsed_seconds": result["elapsed_seconds"],
                "muse_usage": result["muse_usage"], "handoff": str(handoff)})
            result["ledger_recorded"] = True
        except (OSError, ValueError) as exc:
            result["ledger_error"] = str(exc)
    handoff.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    handoff.chmod(0o600)
    compact(result, args.max_output_chars)
    if result.get("ledger_error"):
        return 1
    return 0 if success else (code if code > 0 else 1)


def main():
    with ExitStack() as locks:
        termination = {"signal": None, "waiting": False}
        def on_signal(signum, frame):
            termination["signal"] = termination["signal"] or signum
            if termination["waiting"]:
                raise WorkerTerminated()
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous = signal.signal(signum, on_signal)
            locks.callback(signal.signal, signum, previous)
        return run(locks, termination)


if __name__ == "__main__":
    sys.exit(main())
