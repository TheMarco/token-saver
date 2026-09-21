# Token Saver 0.3.1

Token Saver helps Codex spend less context and effort on avoidable work. It selects relevant source excerpts before broad reads and delegates bounded coding tasks to your installed Meta Muse CLI, while Codex keeps the decisions and final review.

It installs two skills and a reversible instruction block—not a background service or a replacement for Codex's model. You can start entirely locally, add Muse, and enable the Jev API independently.

New in 0.3: optional per-turn Muse model/effort overrides, requested-versus-observed configuration, Git scope evidence, workspace/session locks, and a local acceptance/usage ledger. Unknown measurements stay unknown. See [configuration and evidence setup](docs/EVIDENCE.md) for commands and limitations.

0.3.1 hardens termination cleanup, marks primary measurements stale after new attempts, and caps the whole stdout result rather than only its answer. Full evidence remains on disk; abrupt SIGKILL protection is not claimed.

[Install](#install) · [Muse setup](#set-up-muse) · [Jev setup](#set-up-jev-optional) · [Check your setup](#first-run-checks) · [Everyday use](#everyday-use) · [Troubleshooting](#troubleshooting)

## Overview

Work is divided by role:

- **Astra** (or your configured primary model) keeps planning, difficult decisions, review, and integration.
- **Muse** carries out bounded delegated tasks — investigation, implementation, repetitive edits, tests — and returns compact results the primary reviews before integrating.
- **Jev Context** selects traceable excerpts from large local inputs. Its default backend is local lexical ranking that runs offline; it is not the remote Jev model. The optional TypeSafe Jev API adds semantic ranking of the same excerpts when you configure a key and authorize its use.

## How it can save tokens

- **Read less irrelevant material.** Jev Context returns selected excerpts with file paths and line ranges, instead of feeding whole files or logs into Codex. The originals and an omitted-content manifest remain available.
- **Move bounded work out of the main conversation.** Muse investigates or implements an assigned task and returns compact evidence. Codex reviews that evidence and the actual changes instead of duplicating the entire investigation.
- **Avoid starting over.** Muse follow-ups can reuse the same session. Completed output can be recovered offline without another model call.
- **Avoid unnecessary work.** Focused tests, reusable project maps, and a checkpoint after two unsuccessful fixes reduce redundant runs and unsupported retries.

These are opportunities, not guaranteed savings. Delegation shifts some usage to Meta; optional semantic ranking adds TypeSafe usage. Review, retained history, retries, and provider calls still have costs. Smaller tool output does not establish a subscription-saving percentage or lower total usage across all providers. Tiny tasks stay local when dispatch would cost more. Use the [scorecard](templates/TASK_SCORECARD.csv) to compare similar tasks, including retries and review effort.

## Requirements

- Python 3.10 or newer, standard library only. No `pip install` is needed.
- Codex with user skills and global `AGENTS.md` support.
- Git, and `rg` (ripgrep) for efficient search.
- For Muse delegation: an installed, authenticated Muse CLI. The runner was tested with Muse Code 1.3.0.
- For semantic ranking: your own TypeSafe/Jev credentials. Local ranking needs no account and makes no network call.

Tested on macOS; Linux is a target. The current wrapper is not Windows-supported (process-termination code).

Check your prerequisites with `python3 --version`, `git --version`, and `rg --version`. Install missing tools through your operating system's package manager. You need an existing signed-in Codex installation; this package does not install Codex or supply provider accounts.

## Components

| Installed item | Purpose |
| --- | --- |
| `muse-delegate` skill | Compact CLI runner and delegation instructions; read mode disables shell and file writes, edit mode requires a linked Git worktree |
| `jev-context` skill | Bounded excerpt selection with line references and a manifest of omitted material; local backend offline, API backend optional |
| Marked block in global `AGENTS.md` | Default routing and provider preferences; existing instructions outside the block stay intact, primary model unchanged |

## Install

Start from the already-downloaded or extracted package directory. All installer commands below use that directory as the working directory.

```sh
cd /path/to/token-saver-0.3.1
python3 install.py install --dry-run
python3 install.py install
```

A fresh plain install enables the local context workflow only; automatic Meta and TypeSafe calls default to off. On updates, omitted flags preserve previous choices:

| Command | Effect |
| --- | --- |
| `python3 install.py install` | First install: local filtering only; updates: preserve existing choices |
| `python3 install.py install --muse` | Also permit automatic delegation of task-relevant project excerpts to your Meta account |
| `python3 install.py install --jev-api` | Also permit task-relevant excerpts to the TypeSafe Jev API |
| `python3 install.py install --muse --jev-api` | Permit both |

These flags record your preference; they do not create accounts, buy credits, verify subscription coverage, configure authentication, or force Jev ranking on every read. Re-running install to add a flag preserves unspecified options. The installer makes no network or model calls and never edits `config.toml`, models, reasoning, or speed.

The default Codex home is `~/.codex`, or `$CODEX_HOME` when set. For a custom location, add `--codex-home /absolute/codex-home` after the subcommand. That scope means Codex instances using that home, across local projects and new tasks — not other devices, cloud sync, or teams. Start a new Codex task or session to load the skills and instructions. Project `AGENTS.md` files may override global defaults; inspect conflicts rather than deleting project policy. If a client shows a different skill catalog, the installed global block carries absolute skill paths as a fallback.

For the helper commands below, set this variable in your terminal. If you used `--codex-home`, use that exact directory instead:

```sh
token_saver_home="${CODEX_HOME:-$HOME/.codex}"
```

Verify installation state (checks files and executables only — not network or account validity, and prints no secrets):

```sh
python3 install.py doctor
python3 "$token_saver_home/skills/jev-context/scripts/context_filter.py" doctor
```

Expect JSON showing your Python version, Codex home, `muse`/`git` paths, installed version `0.3.1`, and selected options. After install, always use the installed Jev helper path for credential checks, not the package copy: private settings live beside the installed skill. With a custom home, substitute its `skills/jev-context/scripts/context_filter.py`.

The installer records the original contents of any replaced skill files in `token-saver/state.json` inside the Codex home. It never copies this package's local environment and never touches private `settings.json` files, login state, or API keys. Keep that state file until uninstall if you need the originals restored.

## Set up Muse

The [official Meta setup guide](https://dev.meta.ai/docs/overview) provides this installer:

```sh
curl -fsSL https://dev.meta.ai/install.sh | sh
```

Note that this downloads and executes provider code; inspect the script first if you prefer. Then check the CLI and log in ([auth details](https://dev.meta.ai/docs/muse-code/auth)):

```sh
muse --version
muse login
```

CLI 1.3.0 supports both commands. Follow the browser approval flow for your Meta account. For API-key authentication, `muse auth set --api-key-stdin` accepts a key through standard input, for example from a secret manager; never put a literal secret in command arguments or shell history. An existing `META_API_KEY` or stored key takes precedence over browser login. Verify the account, model, and billing arrangement you intend to use; Token Saver does not guarantee which calls your subscription covers. See [Meta authentication and billing](https://dev.meta.ai/docs/muse-code/auth).

The runner uses your existing Muse login and model configuration. This package does not manage Muse accounts.

Back in the Token Saver directory, enable automatic delegation:

```sh
python3 install.py install --muse
```

Restart Codex after installing Muse, and confirm `command -v muse` works in Codex's terminal too. A working shell login alone does not prove the desktop app can find the executable.

## Set up Jev (optional)

The local backend needs no account or key. For semantic ranking, sign in to [TypeSafe's API-key dashboard](https://console.typesafe.ai/keys) and create a key, following its [quick start](https://docs.typesafe.ai/introduction/quickstart). This is a separate credential from Meta or OpenAI. No Jev CLI, SDK, or additional TypeSafe skill is required: the included helper calls the API directly.

Secure setup, done once with your editor:

1. Create a private directory outside your repositories, then use your editor to create `~/.config/token-saver/jev-api-key` there. Put only the raw key in that file—not in a command or a chat:

```sh
mkdir -p ~/.config/token-saver
chmod 700 ~/.config/token-saver
```

2. After saving the key file, restrict its permissions:

```sh
chmod 600 ~/.config/token-saver/jev-api-key
```

3. Edit the installed `<codex-home>/skills/jev-context/settings.json` to point at it:

```json
{"key_file": "/absolute/path/to/key-file"}
```

Only the path goes in JSON, never the secret, and preserve any existing settings instead of overwriting blindly. A key file persists for GUI apps without shell environment inheritance. Alternatives are the `TYPESAFE_API_KEY` or `JEV_API_KEY` environment variables, or `TYPESAFE_API_KEY_FILE` pointing at a key file; the key file is preferred. Never print or read secrets in checks.

4. Enable API use and check that the installed helper can find the key:

```sh
python3 install.py install --jev-api
python3 "$token_saver_home/skills/jev-context/scripts/context_filter.py" doctor
```

Expect `"key_available": true` and `"network_called": false`. This checks key availability, not validity or billing. The optional remote check below verifies a real call. The `--jev-api` flag preserves any existing Muse opt-in; local ranking remains the normal first choice.

## First-run checks

Run these from the package directory using the installed helpers.

Local smoke test — no network, safe to run:

```sh
python3 "$token_saver_home/skills/jev-context/scripts/context_filter.py" \
  --root "$PWD" --query 'delegation and review' --backend local \
  --budget-chars 6000 --manifest work/local-check.json docs/WORKFLOW.md
```

Expect backend `local` with excerpt paths and line ranges for this package's own workflow doc.

Optional remote smoke — sends this public package doc to TypeSafe and may cost; run only if you accept that:

```sh
python3 "$token_saver_home/skills/jev-context/scripts/context_filter.py" \
  --root "$PWD" --query 'delegation and review' --backend jev \
  --max-candidates 1 --manifest work/jev-check.json docs/WORKFLOW.md
```

Expect backend `jev` and `metrics.jev.scored` above zero. Falling back to local ranking here is not success; inspect the metrics.

Optional Muse check — uses your Meta provider and may consume allowance or incur charges. Create `work/` if needed, then use your editor to create `work/muse-check.txt` containing: `Read VERSION only and report its contents. Do not edit files or use unrelated tools.` Then run:

```sh
python3 "$token_saver_home/skills/muse-delegate/scripts/muse_worker.py" \
  --workspace "$PWD" --prompt-file work/muse-check.txt --max-steps 4
```

Expect status `completed` and the correct version `0.3.1`.

Installer flags guide automatic agent behavior; they do not block direct helper commands. Running a command with `--backend jev` or starting a Muse job explicitly invokes that provider regardless of the installer's opt-in state.

## Everyday use

Start a new Codex task in your project and ask for work normally. The installed instructions encourage the agent to choose a proportionate approach; they are not a background scheduler or a guarantee of delegation on every request. For explicit use, try:

> Use Muse to investigate this bug. Give it a bounded scope, then review the evidence before deciding on a fix.

> Use jev-context to select relevant excerpts from these logs. Start locally and retain references to omitted content.

You can also name `$muse-delegate` or `$jev-context`. A focused file lookup usually needs neither. Once a task is genuinely complete, the instructions do not ask the agent to invent extra tests or improvements.

For measurable delegation, give edit jobs explicit allowed paths and use a stable task ID with an optional local ledger. Review the saved handoff before recording acceptance. Model/effort overrides are optional and apply per turn; installing this package does not select a particular Muse model or maximum effort. [Configuration, scope checks, and ledger commands](docs/EVIDENCE.md) show the complete workflow. Primary-model usage must come from an actual measurement; this is not an automatic Codex token meter.

## How work flows, and its limits

- Delegate substantial, independent tasks with clear acceptance criteria. Keep architecture, ambiguous debugging, security decisions, migrations, and integration with the primary agent.
- Code edits run only in a linked worktree rooted at a Git commit. Uncommitted changes are not copied: transfer only task-relevant changes deliberately, or keep tightly coupled work local. The runner never commits, pushes, deploys, or deletes worktrees; the primary reviews every result — inspect the diff, untracked files, and findings against source, run the checks relevant to the change — before integrating.
- Same-assignment follow-ups reuse the retained job directory with `--resume`. Mode and workspace are inherited and locked; each turn is another provider call, not free (unlike offline `--extract` recovery). Retain the logs and worktree, and never run concurrent turns on one session.
- After two unsuccessful fixes to the same issue, reassess the evidence and approach before another attempt.
- Recommended personal workflow: Astra High with standard speed; XHigh and Ultra are manual choices, never automatic. See [SETTINGS.md](docs/SETTINGS.md).
- Detailed CLI examples, worktree handling, and recovery live in [WORKFLOW.md](docs/WORKFLOW.md) and are not repeated here.

## Troubleshooting

- Skills missing after install: start a new task or session, and check `CODEX_HOME` or the `--codex-home` target. The installed global block lists absolute skill paths.
- Global behavior overridden: inspect project `AGENTS.md` and `AGENTS.override.md`. Global defaults do not erase project policy.
- `muse` missing: check its PATH in Codex's terminal, not only your regular terminal; restart the app after installation. Authentication failures need Muse's login flow, not a sandbox bypass.
- Workspace/session already active: wait for the owning wrapper job to finish or stop it normally. Do not delete active lock files to force another run.
- Model/effort or usage shows `null`: the run did not provide enough evidence. A requested setting is not an observed setting, and unknown usage is not zero.
- Ledger write failed: inspect `ledger_error` and preserve `handoff_file`. The wrapper returns nonzero even if `execution_status` is `completed`; repair the ledger/path, then import the handoff offline instead of rerunning Muse.
- Jev key found in a shell but not Codex: desktop apps may not inherit shell exports. Use the installed skill's `settings.json` with an absolute key-file path.
- Jev falls back to local ranking: inspect `metrics.fallback` and `metrics.jev.errors`, then check the key path, permissions, account access, and connectivity. A successful process exit alone does not establish API success.
- Installer stops on a conflict: a managed file or the managed block was edited. Save those changes outside the managed files or markers, reconcile them, then re-run. Never delete `token-saver/state.json` while installed: it is both the ownership record and the backup of replaced files.

## Updates and uninstall

Run the installer from a newer copy of the package to update. Unspecified provider preferences are preserved, and it stops if a managed file was edited so you can save those changes first. Unrelated files in skill directories remain untouched.

For a managed 0.2 installation, run these commands from the 0.3 package (add your original `--codex-home` if custom):

```sh
python3 install.py install --dry-run
python3 install.py install
python3 install.py doctor
```

This adds the evidence/ledger helpers without changing provider opt-ins or model defaults. Pulling the repository alone does not update installed skills. Keep the install state for safe upgrades and restoration.

Disable automatic provider requests without uninstalling:

```sh
python3 install.py install --no-muse --no-jev-api
```

Preview, then remove:

```sh
python3 install.py uninstall --dry-run
python3 install.py uninstall
```

Uninstall restores the skill files that existed before the first install, or removes only the files it created. It preserves unrelated instructions, private settings, and other files, and stops before changing anything if managed files or the managed block were edited. Empty directories may remain. Provider logins, logs, and worktrees are not removed.

## Privacy

- Installer, tests, and the local backend: nothing leaves the machine through this package.
- Jev API backend: the task query and selected candidate excerpts are sent to TypeSafe.
- Muse worker: the task prompt and repository content Muse reads may go to its configured provider.
- Codex itself follows your own Codex and account configuration; these flags govern only the added Muse and Jev workflow. No authorization is inherited by installing these files: every user enables their own services.
- Logs stay local and are never removed automatically: task prompts, event streams, answers, session logs, and mode-600 resume metadata. Continuing a session can resend prior context to the configured provider.
- The context helper skips common credential paths and avoids sending obvious credential patterns to Jev. Those checks are best-effort, not a secret scanner: select inputs deliberately.

See [PRIVACY.md](docs/PRIVACY.md) for data flow and log details.

## Deeper reading

- [WORKFLOW.md](docs/WORKFLOW.md): direct CLI use, worktrees, resume, and recovery.
- [EVIDENCE.md](docs/EVIDENCE.md): model/effort observations, scope checks, acceptance, local ledgers, and measurement limits.
- [SETTINGS.md](docs/SETTINGS.md): optional speed and reasoning choices, applied manually.
- [OPTIMIZING.md](docs/OPTIMIZING.md): further savings; [TESTING.md](docs/TESTING.md): testing policy; [SKILL_AUDIT.md](docs/SKILL_AUDIT.md): skill overlap review.
- [templates](templates/): task brief, handoff, project map, scorecard; [examples](examples/): editable worker prompts.
- [Codex global and project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md); [Meta coding agents](https://dev.meta.ai/docs/coding-agents).

## Build a shareable archive

From the package directory, run `python3 scripts/build_release.py`. It produces `dist/token-saver-0.3.1.zip` and prints its SHA-256 checksum. The explicit allowlist excludes credentials, private settings, logs, caches, and Git history. Prefer sharing that ZIP over an unreviewed working folder. Contributors can run the offline suite with `python3 -m unittest discover -s tests -v`; end users do not need to run it to install.

Released under the [MIT license](LICENSE). Not affiliated with OpenAI, Meta, or TypeSafe. Provider CLIs and services are not bundled.
