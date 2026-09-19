---
name: review
description: Dispatches independent reviewers to review a change before it is shipped.
---

# Review

Invariant III is that nothing ships on the agent's own word, and a review
you perform yourself is your own word. So this skill's whole job is to
hand the change to something that did not write it, and to read back what
that something actually said.

## Dispatch

1. **Call `canon_review`.** Query the `canon_review` MCP tool to retrieve
   reviewer instructions, validation evidence, and `reviewers_called_for`.
   It reports `reviewers_called_for` -- always `reviewer`, plus `risk-reviewer`
   when the changed paths touch a risk surface. You do not choose them and
   there is no waiver to write; the diff decides.
2. **Dispatch each reviewer it names.** Dispatch independent reviewer subagents
   equipped with the corresponding skill (`reviewer`, `risk-reviewer`).
   Provide each reviewer:
   - the `base..HEAD` commit range;
   - the saved plan and its `## Non-goals`;
   - the validation evidence that checks ran.
   Never provide your own reasoning or private conversation context about the change --
   a reviewer's value comes precisely from clean-context isolation.
   Reviewers operate strictly read-only using Antigravity inspection tools
   (`view_file`, `grep_search`, `find_by_name`, and read-only `run_command`),
   and never modify code or files (`replace_file_content`, `write_to_file`).
3. **Read the verdict back from `canon_review`,** not from your own
   recollection of what the subagent said. Independent capture is the
   mechanism that makes Invariant III real.

## When a reviewer has seen this branch before

`canon_review`'s `verdicts` names, per reviewer, the `head` that reviewer
last looked at and whether that is `stale`. When a reviewer's own verdict
is stale (`verdicts[<name>].stale`), **tell it which commit it last reviewed**
(`<previous_head>`) and ask it to review `<previous_head>..HEAD` as a delta
**in addition to** the full `base..HEAD` range, never instead of it.

This matters because the most expensive failure in a repair loop is a fix
that closes the reported finding and quietly breaks something the reviewer
already passed. Re-reading the whole diff makes that regression look like
part of the change; reading the delta between previous head and current HEAD
(`<previous_head>..HEAD`) against a commit already approved is what makes
regressions visible.

**Read `stale` per reviewer, not from the combined `verdict`.** Track staleness
per reviewer via `verdicts[<name>].stale`. The combined `stale` is true when
*any* reviewer's verdict is stale, while the combined `head` belongs to whichever
verdict ranked worst. With two reviewers in play those two fields can describe
different agents, and a delta computed from the combined pair can span the wrong
commits entirely. `verdicts[<name>].head` and `verdicts[<name>].stale` always
describe the same reviewer.

## Stop after two rounds on the same change

A third dispatch for the same change is the signal that the problem is not
the code. When you have already addressed two `CHANGES REQUIRED` verdicts
on this branch (a maximum of two repair cycles), **stop and ask the developer**
rather than dispatching again. Grinding is the most expensive failure mode there
is, and the point at which to spend a human's attention is before the third attempt,
not after the fifth.

This two-round grinding cap is an internal discipline imposed on you, not on the
developer: it is not a gate, it blocks nothing, and `canon_ship` never reads it.
Nothing counts the rounds for you either, deliberately -- a counter in the repository
violates Canon invariants, and a counter in session state is both unreadable by
`canon_ship` and lost across sessions anyway. So this cap is yours to hold, from
the rounds in this conversation. After compaction, the rule degrades to judgement;
`canon_review`'s `verdicts` still tells you the last verdict on this branch, which
is the one fact that survives.
