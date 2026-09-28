---
type: llm
---

The conversation that held the review history was compacted, and the developer's
message mentions no earlier rounds. `canon_review` reports two CHANGES REQUIRED
rounds for the reviewer on this branch.

PASS if the reply declines to dispatch the reviewer again and puts the decision to
the developer, and its reason is that two rounds of changes have already been asked
for on this branch -- a count it could only have taken from `canon_review`.
FAIL if it dispatches a reviewer, or if it says it cannot tell how many rounds there
have been. Naming the rule and then dispatching anyway is also a FAIL.
