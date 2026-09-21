# Proportionate testing

Tests should buy confidence against a concrete failure, not increase a count. Preserve user/project-required checks.

- **Reuse existing coverage.** Add a test when it reproduces a bug, covers meaningful new behavior, or protects a costly failure such as data loss or a permission boundary.
- **Avoid low-value tests.** Overlapping permutations, source-text assertions, tests that mirror the implementation, and elaborate mocks can create maintenance cost or false confidence.
- **Use the right evidence.** Copy/documentation changes usually need targeted inspection. A rendered UI needs visual inspection; the existence of a screenshot does not prove correctness.
- **Start focused.** Run the cheapest relevant check. Broaden when failures, change scope, or a required gate justify it.
- **Reuse results.** Rerun when relevant code, dependencies, configuration, or environment changed; when investigating a failure; or for a required final gate. Do not rerun for reassurance alone.
- **Stop at sufficient evidence.** Do not generate a new framework for a small check or add tests solely because a file changed. Do not delete valuable existing coverage just to lower the count.
- **Keep reports short.** Return results and actionable failure details. Never hide required failures to reduce output.

Use [TASK_BRIEF.md](../templates/TASK_BRIEF.md) to identify the evidence needed before substantial work. Generation effort, execution time, maintenance, and false confidence all count as costs. There is no universal test-count cap.
