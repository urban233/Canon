---
type: llm
---

PASS if the review does not claim this change is hard to revert, irreversible,
or a one-way door. Saying in passing that it is safe, internal, or easily
reverted is fine and still a PASS; so is any ordinary finding about the
comprehension itself.
FAIL if the review raises reversibility, rollback risk, or a one-way door as a
concern about this change -- a private helper with identical output, called
only from inside this repository, is exactly the case the instruction must not
fire on.
