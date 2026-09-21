---
name: jev-context
description: Select compact, traceable excerpts from large local code or text inputs before reading them into context. Use for broad repository discovery or large saved logs; supports local ranking and optional TypeSafe Jev ranking.
---

Use ordinary `rg` and bounded reads for focused work. For large candidate sets, run `scripts/context_filter.py` with a task query and explicit files (or `--files-from` a newline-delimited list). Resolve the script relative to this skill directory. It has no third-party dependencies.

```sh
python3 /path/to/jev-context/scripts/context_filter.py --query 'refresh token expiry' --root /path/to/repo --files-from work/candidates.txt --manifest work/context-index.json
```

The default backend is local and makes no network calls. Add `--backend jev` when TypeSafe is configured and sending the supplied files to TypeSafe fits the user's authorized task. It reads `TYPESAFE_API_KEY` or `JEV_API_KEY`, or a private `--key-file` containing the raw key or a simple assignment to either name. The file path can also be configured with `TYPESAFE_API_KEY_FILE` or `settings.json` beside this skill (field `key_file`). Do not print keys or put them in command arguments. `doctor` reports availability only.

Jev ranks a bounded set of excerpts and caches decisions by content, query, and pinned model. It does not summarize. Output reports omitted and unscored candidates; these are unknown, not irrelevant. Uncertain Jev answers get priority for inspection. Read original referenced lines and relevant callers before editing; broaden discovery when evidence is insufficient. For exhaustive requests, inspect all required material rather than relying on selection. Do not filter user instructions, permission decisions, or mandatory check failures.

Use `--budget-chars` to control the complete printed result. Oversized inputs and credential-like files are skipped explicitly. The index preserves paths and line ranges for omitted material. Character reduction is a measurement of this tool's output only, not total Codex token or subscription savings.

If the API fails, the helper reports local fallback. Do not present local or fixture results as Jev quality validation. Inspect the metrics before drawing conclusions. Try local ranking first; use Jev when semantic relevance warrants its extra cost and latency.
