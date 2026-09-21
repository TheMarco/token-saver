# Further optimization

The objective is successful work per unit of spend, including review and retries. This package does not measure a before/after savings percentage.

## Start with the largest avoidable costs

1. **Route whole bounded tasks.** Astra owns the decisions and final acceptance; Muse does delegated discovery, implementation, and tests. Give Muse paths and acceptance criteria before Astra reads every candidate file. Review the returned evidence and relevant diffs instead of repeating the entire investigation.
2. **Keep task histories focused.** Start a fresh task when the objective changes substantially or a previous investigation has become stale. Carry forward a short handoff with the current goal, exact files/commits, key decisions, known failures, and next check. Retain useful ongoing context rather than splitting every small step into a new task.
3. **Audit overlapping skills and plugins.** Several skills doing the same job can add discovery text and ambiguous routing. Keep one preferred workflow per recurring need; disable unused skills without deleting them, or make occasional skills explicit-only to prevent unwanted activation. Explicit-only is a routing control, not a guarantee that all metadata disappears. Skills load progressively, so do not assume every installed skill's full body is always in context. Measure the effect; do not disable tools needed for the current task. [Official skill configuration](https://learn.chatgpt.com/docs/build-skills)
4. **Make acceptance criteria observable early.** Agree on the behavior and how to check it before implementing. For visual or architectural changes, validate one representative case and its integration constraints before duplicating it across systems. This is often more valuable than optimizing the prompt around repeated failed attempts.
5. **Use proportionate verification.** Run the focused checks that establish the changed behavior; broaden when failures or risk justify it. Reuse passing results until the inputs change. A syntax check is not a substitute for inspecting a visual result.
6. **Control output before it reaches the primary model.** Save verbose logs to files. Return concise failures, source paths, and summaries. Use local search before Jev/API ranking, and avoid a second provider call just to recover a result already on disk.

Do not increase delegation just to maximize the number of agents. A small local operation can cost less than prompt construction, worker startup, waiting, and review. Provider quotas, prices, output tokens, caching, and retries can change the economics.

## Fix loops, maps, and mechanical work

- After two unsuccessful fixes to the same problem, reassess evidence, assumptions, why another attempt differs, and approach viability before continuing. Ask the user only when new authority or a choice is needed.
- Reuse a tiny verified [project map](../templates/PROJECT_MAP.md) (exact paths, entry points, working commands, pitfalls, last verified revision/date); inspect affected originals and refresh stale entries. Not a growing diary.
- Prefer deterministic existing scripts for recurring mechanical work; add a helper only when a concrete repeat justifies its cost.
- Continue the same Muse assignment with `--resume` rather than repeating discovery; keep its original workspace/mode and verify intervening changes. See [workflow](WORKFLOW.md). This is another provider turn, not free output recovery.
- Consider [standard speed and the High-reasoning reference setup](SETTINGS.md). They are opt-in settings, not changes the installer silently applies. Medium is an optional experiment for routine coordination; users choose any higher effort explicitly.

## Measure a small sample

Reusable materials: [task brief](../templates/TASK_BRIEF.md), [handoff](../templates/HANDOFF.md), [project map](../templates/PROJECT_MAP.md), [testing policy](TESTING.md), and [skill/plugin audit](SKILL_AUDIT.md). Use them when useful, not as mandatory paperwork for tiny tasks.

For the next five to ten comparable tasks, record:

- Task type and whether it met its acceptance criteria.
- Who did the work: primary only, Muse, or a combination.
- Wall time, provider usage when reported, retries, and primary review effort.
- Whether selected context omitted something needed later.

Compare similar tasks, not a trivial delegated lookup against a difficult direct implementation. Missing usage is unknown, not zero. Distinguish total provider usage from Codex subscription usage; external delegation can shift consumption without reducing total work.

Keep routing as a user preference, independent of the helper scripts. A later model release can justify a new comparison; no future model's price or capability is assumed here.

Copy [TASK_SCORECARD.csv](../templates/TASK_SCORECARD.csv) into `work/` and fill one row per task. Routes: `astra`, `muse`, `mixed`; outcomes: `passed`, `failed`, `blocked`. Enter provider-reported task token totals only; leave unavailable values blank. Do not substitute character counts or subscription percentages. Keep notes brief and free of secrets. This scorecard requires no telemetry service or account access.
