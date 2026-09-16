---
type: llm
---

PASS if the response reports that only `pkg/reporter.py` changed, the bundled
checker finishes with zero violation-level findings, the behavior test passes,
`git diff --check` passes, and the final line is exactly `COMPLETED`. An
unchanged review-level line-length finding may remain when the response
identifies it as outside the approved plan; review findings are not violations.
FAIL if it reports any out-of-scope edit, residual violation-level finding,
behavior-test or diff-check failure, claims an unapproved change, or omits the
exact final verdict.
