---
name: review
description: Dispatch Canon's independent reviewer subagents for this branch and read their verdicts back from canon_review. Use once a change is built and verified, before shipping. This skill only dispatches and reads back -- the review itself runs inside the subagent, in a fresh context, and never in this session.
---

# Review

Invariant III is that nothing ships on the agent's own word, and a review
you perform yourself is your own word. So this skill's whole job is to
hand the change to something that did not write it, and to read back what
that something actually said.

## Dispatch

1. **Call `canon_review`.** It reports `reviewers_called_for` -- always
   `reviewer`, plus `risk-reviewer` when the changed paths touch a risk
   surface. You do not choose them and there is no waiver to write; the
   diff decides.
2. **Dispatch each reviewer it names**, giving it the `base..HEAD` range,
   the saved plan and its `## Non-goals`, and the evidence that checks
   ran. Never your own reasoning about the change -- a reviewer's value
   comes precisely from not having seen it. When `canon_review`'s
   `models` names a model for a reviewer, dispatch it on that model; the
   repository chose it, so it is not yours to change.
3. **Read the verdict back from `canon_review`,** not from your own
   recollection of what the subagent said. The `SubagentStop` hook
   captures it from the subagent's own final message, which is the
   mechanism that makes Invariant III real.

## When a reviewer has seen this branch before

`canon_review`'s `verdicts` names, per reviewer, the `head` that reviewer
last looked at and whether that is `stale`. When a reviewer's own verdict
is stale, **tell it which commit it last reviewed** and ask it to review
`<head>..HEAD` as a delta **in addition to** the full `base..HEAD` range,
never instead of it.

This matters because the most expensive failure in a repair loop is a fix
that closes the reported finding and quietly breaks something the reviewer
already passed. Re-reading the whole diff makes that regression look like
part of the change; reading the delta against a commit already approved is
what makes it visible.

**After a READY verdict, confirm the delta only.** When a reviewer's own
last verdict is READY FOR HUMAN APPROVAL and its `head` is an ancestor of
HEAD -- you only closed its notes, or touched docs -- it has already
passed everything up to that commit. Ask it to review `<head>..HEAD`
alone and return a fresh verdict. The full range is for repair after
CHANGES REQUIRED, where a fix can break what was passed; after READY
there is nothing unpassed outside the delta, and re-reading the whole
range costs a full round for no new coverage. The verdict is still fresh
at HEAD, so `canon_ship` is satisfied the same way.

**Read `stale` per reviewer, not from the combined `verdict`.** The
combined `stale` is true when *any* reviewer's verdict is stale, while the
combined `head` belongs to whichever verdict ranked worst. With two
reviewers in play those two fields can describe different agents, and a
delta computed from the combined pair can span the wrong commits entirely.
`verdicts[<name>].head` and `verdicts[<name>].stale` always describe the
same reviewer.

## Stop after two rounds on the same change

A third dispatch for the same change is the signal that the problem is not
the code. When you have already addressed two `CHANGES REQUIRED` verdicts
on this branch, **stop and ask the developer** rather than dispatching
again. Grinding is the most expensive failure mode there is, and the
point at which to spend a human's attention is before the third attempt,
not after the fifth.

Every dispatch also bills: the reviewer runs a host review as a
subprocess, and that review widens its own fan-out as the diff grows, so
grinding costs money as well as your attention and the developer's.

This is imposed on you, not on the developer: it is not a gate, it blocks
nothing, and `canon_ship` never reads it. **Take the count from
`canon_review`'s `rounds`**, not from this conversation: it counts each
reviewer's CHANGES REQUIRED verdicts on this branch, derived from the
verdicts already captured, so it survives a compaction that the
conversation does not. When any reviewer's `rounds` is 2, stop and ask.
