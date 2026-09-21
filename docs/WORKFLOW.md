# Workflow and instructions

The editable global policy is [instructions/global.md](../instructions/global.md). The installer fills in skill locations and the selected provider preferences. The detailed workflows live in each skill's `SKILL.md`; short global rules avoid loading both workflows into every conversation.

## Choose the smallest useful approach

1. A focused question or a small change: use `rg` and bounded source reads directly. For informational requests, inspect existing evidence, answer, and stop; do not start tests or fixes unless requested.
2. Many candidate files or a large saved log: use Jev Context to select traceable excerpts, then read relevant originals before making decisions.
3. A bounded, independent task with clear acceptance criteria: delegate to Muse when enabled only if it replaces primary work and can be reviewed without reconstructing the investigation. Specify the initial check and reasons that permit expanding it. Do useful independent work while it runs.
4. Architecture, ambiguous debugging, security decisions, migrations, and integration: keep ownership with the primary Codex agent.

With the Astra/Muse profile enabled, Muse handles delegated work that would otherwise go to Sol/Terra/Luna workers. Do not automatically fall back to those models. If Muse is unavailable or a step needs Codex-specific tools, the primary agent handles the necessary work and reports the fallback. Tiny tasks stay local. Avoid multiple agents repeating the same task. Permit at most three workers and no recursive delegation. Revisit model routing when the user changes the preference rather than guessing future model capabilities.

## Muse directly

See [Evidence](EVIDENCE.md) for optional model/effort overrides, allowed-path checking, locks, and acceptance/usage records. These preserve defaults and do not automatically accept work or run additional tests.

These examples run from the extracted package. Installed helpers are under your Codex home's `skills` directory. Adapt the examples in `examples/` into a concrete task file before dispatching.

```sh
python3 skills/muse-delegate/scripts/muse_worker.py \
  --workspace /absolute/project \
  --prompt-file /absolute/task.txt
```

Read mode disables Muse's shell and direct file-write tools and asks it to use `read_file`/search. It also disables web tools. Prompt restrictions on unrelated tools and remote actions are instructions, not a universal network or security boundary. The CLI sandbox and approval mechanism remain enabled.

For code changes, inspect the current checkout and choose a task base before creating a worktree:

```sh
git -C /absolute/project worktree add -b codex/example-task /absolute/worker-directory HEAD
python3 skills/muse-delegate/scripts/muse_worker.py \
  --mode edit --workspace /absolute/worker-directory \
  --prompt-file /absolute/task.txt \
  --allow-path src/example.py --allow-path tests/test_example.py
```

`HEAD` is the current commit, not uncommitted work. Transfer only relevant changes deliberately when they are needed. The runner requires the worktree root; it refuses editing the main checkout. It does not integrate, commit, push, or delete worktrees for you. A worktree separates file changes but still shares repository metadata and the machine.

The helper requests per-run workspace trust so Muse loads project rules. It does not persist trust or disable sandboxing. For private/non-Git files where worktree isolation is unavailable, use read-only recommendations and have the primary agent edit.

The default budget is 24 model steps and 600 seconds. Set `--max-steps` or `--timeout` for a task that needs different limits. `--max-output-chars` bounds the entire stdout JSON, including its newline (minimum 3 characters). Large results return selected status fields, change counts, and a `handoff_file` pointer when space permits; full evidence stays on disk. If even the pointer cannot fit, stderr reports its path. Stderr diagnostics are separate from this stdout budget. Open the handoff when `output_truncated` is true; tiny budgets may omit even that flag. Process exit success means Muse completed a response, not that its claims or code are correct.

Each job prints the temporary log directory and returns JSON with the answer, completion state, session ID, model, and retained output paths. Read only the final result normally. Recover output without another model call:

```sh
python3 skills/muse-delegate/scripts/muse_worker.py --extract /absolute/job/events.jsonl
muse export --session SESSION_ID --out /absolute/export.json
python3 skills/muse-delegate/scripts/muse_worker.py --extract /absolute/export.json
```

On an error or timeout, inspect `reason`, `stderr_tail`, and the saved logs before retrying. A repeated expensive failure is a reason to work locally. Never disable sandboxing just to make an unattended job succeed.

For corrections within the same assignment, continue its session rather than redoing discovery:

Replace example allowed paths with the assignment's actual ownership. If recording usage, pass the same `--ledger` path on each follow-up; the ledger path is not inherited. Task ID and allowed paths are inherited, while model/effort overrides must be repeated when required.

```sh
python3 skills/muse-delegate/scripts/muse_worker.py \
  --resume /absolute/prior-job-directory --prompt-file /absolute/followup.txt
```

Use the prior JSON result's `logs` directory; the runner reads its `session.json`. Workspace and read/edit mode are inherited and cannot change. Edit mode still requires the original linked worktree. Each follow-up has separate logs and reuses the session ID; it makes another provider call, unlike `--extract`. Retain the worktree, job metadata, and Muse session logs; do not run simultaneous turns on one session. Older jobs without metadata are not resumable through this wrapper. Never synthesize a metadata file to bypass the boundary. Inspect relevant intervening changes and send only the needed correction. Failure does not silently create a new session.

After a code job, inspect tracked and untracked changes, compare findings against source, run relevant checks, and integrate only the task's changes. Retain the worktree until the changes are accepted.

## Jev Context directly

Start with explicit candidate paths identified by ordinary search. The tool does not crawl repositories automatically.

```sh
python3 skills/jev-context/scripts/context_filter.py \
  --root /absolute/project --query 'refresh token expiry' \
  --budget-chars 12000 --manifest /absolute/work/context-index.json \
  src/auth.py tests/test_auth.py
```

For a longer list, use `--files-from /absolute/candidates.txt` with one path per line. Output includes file names and original line ranges. The manifest tracks omitted chunks without storing their full text. Selection is not an exhaustive review. If no excerpts fit a small budget, increase it or choose narrower files. Never use selection to discard user instructions, required check failures, or material required for an exhaustive task.

Local ranking is lexical and works offline. Add `--backend jev` only when API use is authorized and semantic ranking is useful. The helper uses `TYPESAFE_API_KEY` or `JEV_API_KEY`, or a private key file supplied via `--key-file` or `TYPESAFE_API_KEY_FILE`. The file must have no group/other permissions (`chmod 600 /absolute/private/key-file`). It accepts a raw key or a literal assignment to either supported key variable. Do not put the key in command arguments or tracked files.

An optional private `settings.json` beside `SKILL.md` can contain a `key_file` path. No such settings are distributed; the installer preserves existing settings. `doctor` checks availability without revealing the key.

The API model is pinned in `context_filter.py` (currently `jev-1.13.0`). Cache entries last seven days; `--cache-dir` selects their location. Remote failures return explicit fallback metadata and retain local ranking. Treat omitted, unscored, and uncertain chunks as unknown, not irrelevant. Output character reduction is not a measurement of overall Codex usage.

## Troubleshooting

- Skills missing: start a new Codex task/session and check `CODEX_HOME` or `--codex-home`. The installed global block also provides exact skill paths.
- Global behavior overridden: inspect project `AGENTS.md`/`AGENTS.override.md`. Global defaults do not erase project policy.
- `muse` missing or unauthenticated: install/login through Muse's own supported workflow. The package does not manage accounts.
- Headless approval or tool errors: inspect the saved error and handle the necessary action through the normal permission flow. Fall back to local work if appropriate.
- Installer conflict: preserve local modifications outside the managed files/block, then reconcile them before re-running. Do not discard your install state.
