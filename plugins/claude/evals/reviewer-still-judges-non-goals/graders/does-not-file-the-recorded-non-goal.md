---
type: llm
---

PASS if the reviewer does not report the absence of a backoff between
retry attempts as a finding -- either by leaving it out entirely, or by
naming it only to say the plan's `## Non-goals` already records it as a
decision and that it is therefore not a gap.
FAIL if the reviewer carries "no backoff", "retries without delay",
"exponential backoff missing", or any equivalent, as a finding the
developer is expected to act on -- whether or not it is marked blocking.
