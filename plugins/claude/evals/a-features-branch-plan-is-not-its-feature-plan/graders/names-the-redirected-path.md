---
type: regex
target: trace
# The deterministic floor under the judge in
# reads-the-branch-plan-not-the-feature-plan.md, and the canary for the
# whole case. The redirected path reaches the run either from the
# SessionStart context Canon opens with -- verified locally against this
# fixture, `session_start._plan_status` returns "approved
# (.canon/plans/branches/features/public-permalinks.md)" -- or from the
# model reading the file itself. If it never appears at all, Canon's
# hooks did not run and no grader here says anything about the model.
pattern: '\.canon/plans/branches/features/public-permalinks\.md'
---
