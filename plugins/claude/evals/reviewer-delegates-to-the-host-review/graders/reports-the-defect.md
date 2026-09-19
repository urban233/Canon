---
type: llm
---

PASS if the review reports that `average` now excludes the last element
from the sum while still dividing by the full length of `values`, so it
returns a wrong result -- in any wording that makes the arithmetic error
clear, and regardless of whether it also says the change contradicts the
plan's `## Non-goals`.
FAIL if the review never identifies the wrong-result defect, or treats
the slice as a legitimate optimisation.
