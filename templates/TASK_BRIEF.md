# Bounded task brief

Use for substantial or uncertain work. A tiny change can use a sentence.

- **Outcome:** What user-visible behavior changes, and what observation proves it works?
- **Scope:** Which files may change? What is outside this task?
- **Owner:** Primary decision/review owner and delegated worker, if useful.
- **Starting evidence:** Relevant sources, findings, current code state, and checks already performed.
- **Verification budget:** Name the smallest relevant existing check and the failure, affected dependency, risk, or required gate that would justify expanding. Add tests only for concrete gaps; preserve required checks.
- **Representative case:** For uncertain visual/structural work, validate one case in the actual environment before expanding.
- **Reassessment:** What evidence invalidates this approach? Reassess assumptions when repeated attempts fail.
- **Return:** Concise changes/findings, paths, checks, failures, and remaining uncertainty.

Completion means the outcome is established; additional tests are not a separate goal.
