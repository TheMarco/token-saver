# Optional Codex defaults

The installer does not edit `config.toml`, switch models, or change reasoning/speed. These are explicit, user-selected options, independent of enabling Muse or Jev.

## Standard speed

Choose standard speed in the app, or `/fast off` in the CLI. To remove a saved Fast default, remove the top-level `service_tier = "priority"` or `service_tier = "fast"` line from your Codex home's `config.toml`. Do not replace the whole file or edit unrelated project/provider settings. Check for a selected profile or task-specific override if Fast remains enabled. Existing tasks can retain their settings; verify the selector or `/fast status` in the task you actually use.

This changes processing speed, not the selected model or its reasoning level. As of 2026-09-21, Codex lists Astra Fast mode at 2.5 times the standard credit rate, using included limits faster. Standard speed reduces the rate charged for equivalent tokens; it does not reduce the number of tokens. API billing differs. [Official speed documentation](https://learn.chatgpt.com/docs/agent-configuration/speed)

## High reasoning as the reference default

Back up `config.toml`, then change or add this top-level key before any `[table]` headings:

```toml
model_reasoning_effort = "high"
```

Keep your chosen primary model. The reference workflow uses Astra on High because it retains the difficult decisions and reviews while Muse handles delegated work. This is a practical starting point, not a measured optimum. Select XHigh or Ultra yourself for tasks where the additional effort is warranted; Token Saver does not automatically change the current task's reasoning level. Existing tasks can retain their prior setting.

Medium remains an optional experiment for routine coordination. Compare a few similar tasks, including review time and retries, before adopting it. Do not lower effort in the middle of difficult work just to satisfy a blanket savings rule.

[Official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

## Keep rollback narrow

Restore only the setting you changed to its previous value. A full-file backup is a recovery aid, not a reason to overwrite later unrelated edits. New tasks generally pick up defaults; always check the actual task settings rather than assuming a file edit changed an ongoing run.
