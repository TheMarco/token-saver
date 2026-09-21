# Data flow and local files

The package contains code and instructions, not credentials or provider access. Every recipient supplies their own accounts and decides which services to enable.

| Component | What leaves the machine | Local artifacts |
| --- | --- | --- |
| Installer and tests | Nothing | Skills, managed instructions, restore state; temporary test fixtures |
| Jev Context, local backend | Nothing from this helper | Selected output and a source manifest |
| Jev Context, API backend | Task query and selected candidate excerpts sent to TypeSafe | Manifest and cached relevance decisions |
| Muse worker | Task prompt and repository content read by Muse may go to its configured provider | Task prompt, JSONL events, stderr, final answer, Muse's own session logs |

Codex itself follows the user's Codex/account configuration; this package does not turn Codex into an offline model. Its flags govern the additional Muse/Jev workflow.

Automatic provider calls require installer opt-in (`--muse`, `--jev-api`) or explicit authorization in a task. No personal authorization from the original author's setup is inherited by installing these files. Opt-ins permit task-relevant excerpts, not unrelated secrets or unrestricted remote actions. Provider data handling, pricing, retention, and subscription terms are governed by each user's provider agreement; this package does not guarantee them.

The context helper skips common credential paths and avoids sending obvious credential patterns to Jev. Those checks are best-effort, not a secret scanner. Select inputs deliberately. A stored query or file path can itself be sensitive even when source text is omitted.

Muse logs can contain private source code and intermediate messages. The wrapper prints their unique temporary directory, and Muse also keeps its own normal session log. Resume metadata (`session.json`, mode 600) records session ID, workspace, and read/edit mode; a follow-up also retains an offline export (`resume-check.json`) of earlier session history. Continuing a session can resend that prior context to the configured provider. None of these files are automatically removed by uninstall. Check the provider CLI's own log/retention controls and remove only specific logs you no longer need. Deleting logs or the original worktree can prevent resume.

Install state lives at `<codex-home>/token-saver/state.json`, mode 600. It contains the original versions of replaced skill files and the generated global block so uninstall can restore ownership safely. Keep it private and retain it while the package is installed.

The release builder includes only the explicit source allowlist. It excludes environment files, key settings, auth state, backups, caches, session logs, test workspaces, and Git history. Review additional files before sharing a whole working folder; prefer the generated ZIP for a predictable distribution.
