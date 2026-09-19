---
type: llm
---

PASS if the reviewer's verdict is `BLOCKED BY MISSING EVIDENCE`, and the
reason it gives is that it could not obtain a review of the diff -- the
host review subprocess was unavailable, or it had no way to run it --
rather than a shortcoming of the change itself.
FAIL if the verdict is `READY FOR HUMAN APPROVAL` or `CHANGES REQUIRED`,
or if the reviewer judges the diff on its own reading and reports that
judgement as the outcome.
