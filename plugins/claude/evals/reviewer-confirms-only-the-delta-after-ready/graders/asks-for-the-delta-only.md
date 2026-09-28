---
type: llm
---

The reviewer's last verdict on this branch was READY FOR HUMAN APPROVAL, against a
commit HEAD has since moved past, and the only change since closes that reviewer's
own non-blocking docs note.

PASS if the reviewer was dispatched to review only what changed since the commit it
approved -- the delta from that commit to HEAD -- and to return a fresh verdict.
FAIL if the reviewer was also asked to re-review the full range of the branch from
its base, or if the reply treats this as a first review. After a READY verdict the
full range has already been passed; re-reading it is the cost this rule removes.
Also FAIL if no reviewer was dispatched at all: a fresh verdict at HEAD is still
required.
