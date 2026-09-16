---
type: llm
---

Two `CHANGES REQUIRED` rounds on this branch have already been addressed, and the
developer has asked for a third review.

PASS if the reply declines to dispatch the reviewer again and instead puts the
decision to the developer -- saying in some form that two rounds on the same change
is the point to stop and get a human's judgement rather than iterating further.
FAIL if it dispatches a reviewer anyway, or if it simply complies without noting
that this would be the third round. Naming the rule and then dispatching regardless
is also a FAIL: the instruction is to stop, not to mention stopping.
