# Configuration and evidence

These features do not change Muse defaults, upload telemetry, or establish a savings percentage. Examples run from the package root. Installed scripts live under `$CODEX_HOME/skills/muse-delegate/scripts` (default `~/.codex`).

## Per-turn settings

```sh
python3 skills/muse-delegate/scripts/muse_worker.py \
  --mode edit --workspace /absolute/linked-worktree --prompt-file /absolute/task.txt \
  --model YOUR_MUSE_MODEL_ID --reasoning-effort max \
  --allow-path src/example.py --allow-path tests/test_example.py \
  --task-id example-fix --ledger /absolute/private/example.ledger.jsonl
```

Choose a model available to your account. Omit model/effort flags to leave those settings to Muse. Repeat overrides on resume if required; Token Saver does not establish session defaults, though Muse may retain session settings.

`configuration` reports requested/observed values and exact-identifier matches. Missing observations are `null`, never assumed matches. Aliases may need review. The current CLI can omit effort: requesting `max` does not prove it ran at `max`. `cli_version` describes the binary, `session_build_version` the exported session's original build; neither is a model version.

## Completion versus acceptance

Each job saves `handoff.json`. `execution_status` (and legacy `status`) describes CLI completion only. `acceptance_status` starts `unreviewed`; `checks` is null. No extra acceptance tests run automatically, and Muse's test claims do not establish acceptance.

`changes` records base/final revisions, pre-existing dirty files, changed/untracked paths, and scope violations. Repeat `--allow-path` for exact repository-relative files; a trailing `/` permits a directory tree. No globs or traversal. Omission means scope is unverified. Read jobs flag any observed change. Resumes inherit task ID and allowed paths unless scope is explicitly supplied again.

Snapshots compare dirty-file contents, modes, and index state. Unchanged pre-existing edits are not attributed to Muse; renames include both paths. Ignored files, temporary edits restored before capture, external effects, and shared Git metadata are not fully audited. Scope checks are review aids, not a sandbox or proof of authorship. Inspect `review_flags`, actual diffs, and appropriate checks before accepting.

Nonblocking locks cover the canonical workspace and session, including resume preflight and evidence capture. They coordinate Token Saver jobs, not editors or direct Muse invocations. SIGTERM, SIGINT, and SIGHUP trigger worker process-group cleanup while locks remain held; a worker that ignores termination is killed after a short grace period. Repeated termination signals do not bypass cleanup. Lock files remain to avoid inode races; do not delete active locks. Abrupt SIGKILL or a wrapper crash can still leave an orphan worker after locks release: inspect and stop the worker before retrying. Detached processes outside the worker's group are not covered. macOS/Linux only.

## Local ledger

`--ledger` is opt-in. Keep it outside the repository; this package ignores `*.ledger.jsonl`, not arbitrary filenames. Ledgers use locked appends and private permissions. They store counters, handoff paths, and review notes, not prompts/answers. Separate runtime logs still contain project material. Nothing is uploaded automatically.

Record a review after checking the work:

```sh
python3 skills/muse-delegate/scripts/task_ledger.py review \
  --ledger /absolute/private/example.ledger.jsonl \
  --task-id example-fix --attempt-id ATTEMPT_ID \
  --decision accepted --evidence 'Reviewed diff; focused existing tests passed.'
```

Use `rejected` when appropriate. Failed execution cannot be accepted. Completed turns can still have failing tests: the reviewer must reject them. Notes are reviewer assertions, not machine proof the cited tests ran. Reviews append without changing the handoff. The latest attempt's latest review determines acceptance; follow-ups count as `additional_attempts`, not necessarily retries.

Import a handoff if the original run omitted `--ledger`:

```sh
python3 skills/muse-delegate/scripts/task_ledger.py record \
  --ledger /absolute/private/example.ledger.jsonl --handoff /absolute/job/handoff.json
```

Identical imports are idempotent. Conflicting duplicates and malformed records fail explicitly.

Import historical handoffs in execution order: the ledger uses first-recorded attempt order, not timestamps, to select the latest attempt. Repeat `--ledger` on resumed runs; its path is not inherited. If recording fails, the wrapper retains its handoff and reports `ledger_error` with a nonzero exit code. Fix the path or malformed ledger and import the handoff; do not repeat a model call solely to recover bookkeeping.

Record primary usage only with a measured **whole-task** total including planning, reviews, and retries:

```sh
python3 skills/muse-delegate/scripts/task_ledger.py primary \
  --ledger /absolute/private/example.ledger.jsonl --task-id example-fix \
  --total-tokens 12345 --evidence 'Provider measurement covering the whole task.'
python3 skills/muse-delegate/scripts/task_ledger.py summary \
  --ledger /absolute/private/example.ledger.jsonl
```

The number is illustrative. Omit `--total-tokens` when unavailable. A primary measurement records the attempt IDs covered at that point. A later unique execution makes it stale: `primary_tokens`, complete averages, and complete cross-provider totals become null until a refreshed whole-task measurement covers all attempts. Duplicate imports do not invalidate coverage. The summary retains the previous measurement and covered IDs with `primary_measurement_status: "stale"`; the append-only ledger preserves history. Legacy measurements without coverage IDs are interpreted against attempts preceding them in ledger order. Token Saver does not scrape Codex transcripts or infer usage from characters, account percentages, or elapsed time.

Muse usage comes from an offline export, filtered to the current run and deduplicated by source record ID. Reasoning tokens are not added again to output. Because cache conventions vary, combined totals are derived only when every reported completion explicitly has zero cache counters. Otherwise totals remain unknown while raw counters are retained.

**Coverage:** reported foreground Muse completions only. Background/reminder agents, unreported failed calls, and other processes may be absent. `total_cross_provider_tokens` combines recorded primary and foreground Muse totals, not an account bill. Missing totals stay null; known partial sums and missing counts are separate. Elapsed time covers wrapper turns, not human review.

Primary tokens per accepted task is reported only when every accepted task has a primary measurement. The measured-subset average has a separate coverage count. Compare comparable accepted tasks against a baseline; partial data and moving usage to Muse do not establish percentage savings. Jev metrics remain separate for now.
