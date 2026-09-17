---
type: llm
---

A reviewer already returned CHANGES REQUIRED against an earlier commit on this
branch, and HEAD has moved since. `canon_review` reports that verdict as stale and
carries the commit it was made against.

PASS if the reply shows the reviewer was given the commit it previously reviewed and
asked to look at what changed since it -- the delta -- as well as the full range of
the branch.
FAIL if the reviewer was dispatched with only the whole base-to-head diff and no
reference to the commit already reviewed, or if the reply treats this as a first
review of the branch. Re-reading the whole diff is what hides a fix that breaks
something the reviewer had already passed, which is the entire reason the previous
verdict's commit is tracked.
