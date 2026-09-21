---
name: muse-delegate
description: Delegate bounded repository investigation, implementation, or tests to the user's installed Meta Muse CLI, returning compact results for Codex review. Use when this saves Codex context or work; keep small tasks and primary design decisions local.
---

Use Muse as an external worker. The primary Codex agent owns scope, judgment, integration, and final verification. Use the user's explicit task request or installed global preference to establish authorization for sending task-relevant excerpts to Meta. Do not infer consent from this skill's presence. Honor project-specific restrictions and normal execution permissions. Do not change Muse authentication or model defaults.

## Dispatch

Create a short prompt file with the assignment, relevant paths, acceptance criteria, checks, and exclusions. Include only necessary context. For discovery, provide candidate paths when known and request source locations. For edits, assign exact file ownership. Use `apply_patch` to write prompts; do not interpolate them into shell commands. Resolve the helper relative to this skill directory; the examples below assume the default Codex home. With a custom `CODEX_HOME`, use its `skills/muse-delegate/scripts/muse_worker.py` instead.

Read-only investigation (shell and direct file writes disabled):

```sh
python3 ~/.codex/skills/muse-delegate/scripts/muse_worker.py --workspace /absolute/project --prompt-file /absolute/task.txt
```

For implementation, first create a linked Git worktree from the intended commit using the available worktree tool or `git worktree add`. Use branch prefix `codex/`. Worktrees do not copy uncommitted changes: explicitly transfer only task-relevant changes when needed, or keep tightly coupled work local. Then:

```sh
python3 ~/.codex/skills/muse-delegate/scripts/muse_worker.py --mode edit --workspace /absolute/linked-worktree --prompt-file /absolute/task.txt
```

Edit mode rejects the main checkout. A worktree isolates file changes, not external side effects; the prompt forbids pushes, commits, deployments, messages, and recursive delegation. The CLI sandbox stays enabled. The requested workspace is trusted for this run so its project rules load; this does not persist trust or disable sandboxing. For non-Git projects, use read-only recommendations or perform edits locally. Approval or environment failures are blockers to inspect, not reasons to disable the sandbox.

The runner uses the existing Muse login/model, permits 24 model steps, and times out after 10 minutes. Override `--max-steps` or `--timeout` for a task that warrants it. It saves events, stderr, prompt, and full result in a unique temporary directory, prints a compact JSON result, and returns nonzero for failure, timeout, or missing completion. Start with a short shell yield and use normal session polling so the user can still receive progress. Do independent primary work while Muse runs. Never rerun a successful job just to retrieve output: use `--extract /absolute/events.jsonl` or `muse export` for offline recovery.

## Accept results

For a follow-up on the same assignment, reuse the retained job directory:

```sh
python3 ~/.codex/skills/muse-delegate/scripts/muse_worker.py --resume /absolute/prior-job-directory --prompt-file /absolute/followup.txt
```

Resume submits another model turn with the same session ID; it is not free output recovery. Include only the correction/new evidence and any narrower file ownership. The helper inherits and locks the original workspace and read/edit mode, rechecks edit worktree isolation, and saves this turn in a new log directory. It requires `session.json` produced by this runner; older jobs must start fresh or use Muse's interactive resume. Retain the original worktree and Muse session logs. Never fabricate metadata, resume unrelated work, or run concurrent turns on the same session. Existing context is useful, not proof the files are unchanged: inspect relevant diffs since the prior turn. If a resume fails, inspect it before starting a fresh job; do not silently restart and repeat work. After two unsuccessful fixes to the same issue, reassess the evidence and approach before another attempt.

Read the compact result and any reported errors. Open full `result.txt` when output was truncated. Treat findings as unverified until checked against source; inspect changed files, new/untracked files, and Git diff before integration. Run the checks relevant to the change. Integrate only the approved task scope; retain the worktree until accepted. Do not let Muse commit or push on the user's behalf.

Avoid loading raw event streams into Codex. They include reasoning and repeated intermediate messages. If Muse is unavailable, try one targeted fix when justified, then have the primary agent handle necessary work and report the fallback. Under the Astra/Muse policy, do not automatically route to Sol, Terra, Luna, explorer, or mechanical workers. Do not run multiple agents on the same subtask or use delegation for a trivial read.
