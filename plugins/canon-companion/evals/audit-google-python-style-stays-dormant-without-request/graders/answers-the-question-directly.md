---
type: llm
---

PASS if the response simply explains that `add` returns the sum of its two
integer arguments and does not turn the request into a style audit or propose
style remediation.
FAIL if it audits style, produces a remediation plan, asks for approval, or
does not answer what the function does.
