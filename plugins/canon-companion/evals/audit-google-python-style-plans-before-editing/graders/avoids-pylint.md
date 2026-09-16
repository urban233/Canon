---
type: llm
---

PASS if the response neither runs nor recommends installing, configuring, or
satisfying Pylint, and instead treats the bundled checker and available Ruff
checks as authoritative.
FAIL if it invokes or proposes Pylint, or presents Pylint findings as required
remediation.
