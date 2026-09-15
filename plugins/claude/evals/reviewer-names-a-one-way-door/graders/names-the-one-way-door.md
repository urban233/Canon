---
type: llm
---

PASS if the review says this change cannot be cleanly taken back out, or
identifies that it breaks callers already using `slugify(text, "_")` or
`max_length=` -- in either case connecting it to the fact that the package is
published and downstream code already depends on the old signature.
FAIL if the review never raises the compatibility or revertability
consequence of the signature change, or mentions the rename only as a style or
naming observation.
