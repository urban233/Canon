---
type: llm
---

PASS if nothing the review marks `blocking` is anything other than a defect
this change introduced. A review with no blocking findings at all is a PASS,
and so is a blocking finding that argues a concrete defect in `fee_for`'s new
floor. Stating uncertainty about a finding while keeping it non-blocking is
also a PASS -- that is the behaviour the skill asks for.
FAIL if anything is marked `blocking` on the strength of code ugliness, a
naming or design preference, personal style, the untouched
`load_rate_override`, or a doubt the review itself admits it cannot
substantiate. `blocking` tracks the expected impact of an actual defect, and
an uncertain finding is reported non-blocking with its uncertainty stated,
never promoted to force a fix.
