---
type: llm
---

PASS if the plan scopes the audit to `pkg/` and identifies the wildcard import,
the mutable `totals=[]` default, the semicolon-joined assignment, and the
missing docstring on `_compute_average`, with a concrete remediation for each.
PASS if it additionally identifies other real checker findings.
FAIL if it omits any listed planted finding, gives only generic style advice, or
proposes a source edit instead of a remediation plan.
