#!/usr/bin/env python3
"""Offline task evidence. Missing usage is unknown, never zero or an estimate."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import sys


def tokens(value):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError("token counts must be nonnegative integers or null")
    return value


def summarize_events(events):
    tasks = {}
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("task_id"), str) or not event["task_id"].strip():
            raise ValueError("each event needs a nonempty task_id")
        task = tasks.setdefault(event["task_id"], {"attempts": {}, "reviews": {}, "primary_measurement": None})
        kind = event.get("type")
        if kind in ("execution", "review"):
            attempt = event.get("attempt_id")
            if not isinstance(attempt, str) or not attempt.strip():
                raise ValueError("attempt_id is required")
        if kind == "execution":
            if event.get("execution_status") not in ("completed", "failed"):
                raise ValueError("invalid execution status")
            elapsed = event.get("elapsed_seconds")
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("elapsed_seconds must be finite and nonnegative")
            usage = event.get("muse_usage")
            if not isinstance(usage, dict):
                raise ValueError("muse_usage is required; unknown counters must be null")
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                tokens(usage.get(key))
            previous = task["attempts"].get(attempt)
            if previous is not None and previous != event:
                raise ValueError("conflicting duplicate attempt")
            task["attempts"][attempt] = event
        elif kind in ("review", "primary_usage"):
            if not isinstance(event.get("evidence"), str) or not event["evidence"].strip():
                raise ValueError("review/measurement needs evidence")
            if kind == "primary_usage":
                covered = event.get("covered_attempt_ids", list(task["attempts"]))
                if (not isinstance(covered, list) or any(not isinstance(item, str) for item in covered) or
                        len(set(covered)) != len(covered) or not set(covered).issubset(task["attempts"])):
                    raise ValueError("covered_attempt_ids must be unique known attempts for this task")
                task["primary_measurement"] = {"total_tokens": tokens(event.get("total_tokens")),
                                                "covered_attempt_ids": covered}
                continue
            decision = event.get("decision")
            execution = task["attempts"].get(attempt)
            if execution is None or decision not in ("accepted", "rejected"):
                raise ValueError("review must reference a known attempt and valid decision")
            if decision == "accepted" and execution["execution_status"] != "completed":
                raise ValueError("failed execution cannot be accepted")
            task["reviews"][attempt] = decision
        else:
            raise ValueError("unrecognized ledger event")
    rows = []
    for identifier, task in tasks.items():
        attempts = list(task["attempts"].values())
        totals = [a["muse_usage"].get("total_tokens") for a in attempts]
        measurement = task["primary_measurement"]
        stale = measurement is not None and set(measurement["covered_attempt_ids"]) != set(task["attempts"])
        primary_tokens = measurement["total_tokens"] if measurement and not stale else None
        rows.append({"task_id": identifier, "attempts": len(attempts),
            "additional_attempts": max(len(attempts) - 1, 0),
            "elapsed_seconds": sum(a["elapsed_seconds"] for a in attempts),
            "acceptance_status": task["reviews"].get(attempts[-1]["attempt_id"], "unreviewed") if attempts else "unreviewed",
            "primary_tokens": primary_tokens,
            "primary_measurement": measurement,
            "primary_measurement_status": "stale" if stale else "current" if primary_tokens is not None else "unavailable",
            "muse_tokens": sum(totals) if totals and all(v is not None for v in totals) else None,
            "muse_known_tokens": sum(v for v in totals if v is not None),
            "muse_unmeasured_attempts": sum(v is None for v in totals)})
    accepted = [r for r in rows if r["acceptance_status"] == "accepted"]
    measured = [r for r in accepted if r["primary_tokens"] is not None]
    primary_known = sum(r["primary_tokens"] for r in rows if r["primary_tokens"] is not None)
    muse_known = sum(r["muse_known_tokens"] for r in rows)
    complete = bool(rows) and all(r["primary_tokens"] is not None and r["muse_tokens"] is not None for r in rows)
    mean = sum(r["primary_tokens"] for r in measured) / len(measured) if measured else None
    return {"tasks": rows, "accepted_tasks": len(accepted),
        "primary_measured_accepted_tasks": len(measured),
        "primary_tokens_per_measured_accepted_task": mean,
        "primary_tokens_per_accepted_task": mean if len(measured) == len(accepted) else None,
        "primary_unmeasured_tasks": sum(r["primary_tokens"] is None for r in rows),
        "muse_unmeasured_attempts": sum(r["muse_unmeasured_attempts"] for r in rows),
        "primary_known_tokens": primary_known, "muse_known_tokens": muse_known,
        "total_cross_provider_tokens": primary_known + muse_known if complete else None,
        "coverage": "recorded primary task totals plus reported foreground Muse completions only; excludes unobserved background/provider usage"}


def _read(stream):
    stream.seek(0)
    return [json.loads(line) for line in stream if line.strip()]


def append_event(path, event):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        os.fchmod(stream.fileno(), 0o600)
        events = _read(stream)
        if event.get("type") == "primary_usage" and "covered_attempt_ids" not in event:
            event = {**event, "covered_attempt_ids": list(dict.fromkeys(
                item["attempt_id"] for item in events
                if item.get("type") == "execution" and item.get("task_id") == event.get("task_id")))}
        summarize_events([*events, event])  # Validate under the same lock as append.
        if event.get("type") == "execution" and event in events:
            return
        stream.seek(0, os.SEEK_END)
        if stream.tell():
            stream.seek(stream.tell() - 1)
            if stream.read(1) != "\n":
                stream.write("\n")
        stream.write(json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def summarize(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_SH)
        return summarize_events(_read(stream))


def execution_event(handoff, path):
    return {"type": "execution", **{key: handoff[key] for key in
        ("task_id", "attempt_id", "execution_status", "elapsed_seconds", "muse_usage")},
        "handoff": str(Path(path).resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("summary", "record", "review", "primary"):
        command = commands.add_parser(name)
        command.add_argument("--ledger", type=Path, required=True)
        if name == "record":
            command.add_argument("--handoff", type=Path, required=True)
        if name in ("review", "primary"):
            command.add_argument("--task-id", required=True)
            command.add_argument("--evidence", required=True)
        if name == "review":
            command.add_argument("--attempt-id", required=True)
            command.add_argument("--decision", choices=("accepted", "rejected"), required=True)
        if name == "primary":
            command.add_argument("--total-tokens", type=int)
    args = parser.parse_args()
    try:
        if args.command == "record":
            append_event(args.ledger, execution_event(json.loads(args.handoff.read_text()), args.handoff))
        elif args.command == "review":
            append_event(args.ledger, {"type": "review", "task_id": args.task_id,
                "attempt_id": args.attempt_id, "decision": args.decision, "evidence": args.evidence})
        elif args.command == "primary":
            append_event(args.ledger, {"type": "primary_usage", "task_id": args.task_id,
                "total_tokens": args.total_tokens, "evidence": args.evidence})
        print(json.dumps(summarize(args.ledger), indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Ledger: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
