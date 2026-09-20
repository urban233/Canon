# 8. The eval suite belongs to the Claude Code plugin

Date: 2026-09-20

## Status

Accepted.

## Context

Canon holds that an instruction line earns its place through an eval
that fails without it (docs/plan.md §13). `plugins/claude/evals/` holds
21 such cases, and `plugins/canon-companion/evals/` three more.

That rule invites an inference which is wrong: that every platform Canon
ships for therefore needs its own eval suite, and that a port without
one is incomplete. The Antigravity port was assessed against exactly
that inference -- "2 cases against the Claude plugin's 21" was written
up as a production-readiness gap, and a second runner
(`tools/eval_antigravity.py`) was built to close it.

Both the framing and the runner were wrong, and building the runner is
what demonstrated why.

**The suite is a Claude Code capability, not a Canon one.** `claude
plugin eval` is a feature of the Claude Code CLI: it scaffolds the
fixture, runs the turn, applies the graders, and supplies the judge
model for `type: llm`. Canon supplies case files to it. A second
platform does not have that; it has a CLI that can run one prompt.

**The cases are written in Claude Code's vocabulary.** `allowed_tools:
[Read, Glob, Grep]`, `tool_used` graders naming `Bash`, `target: trace`
against a Claude Code transcript. Porting a case means rewriting its
graders for another tool vocabulary, at which point it is a different
case testing a different thing, and the two can disagree without either
being wrong.

**A hand-rolled runner does not degrade gracefully.** The Antigravity
runner, on its first real execution, reported both cases as failures.
Neither was a failure: `agy --print` had auto-denied a permission it
cannot prompt for, the turns produced no output, and a `not_contains`
grader passed vacuously while the `llm` graders failed on an empty
string. A purpose-built harness knows the difference between "the
instructions are wrong" and "the run did not happen". A weekend one has
to be taught, one confound at a time. This project already has one
confounded ablation result on record; a second harness is a second
source of them.

## Decision

**Eval cases live with the Claude Code plugin.** The Codex and
Antigravity ports carry none, and that is complete rather than
outstanding. No second runner is maintained: `tools/eval_antigravity.py`
and `plugins/antigravity/evals/` are removed, and `just eval` remains
the only model-backed check.

What keeps a port's instruction text trustworthy instead is **minimised
divergence**. The four shared skills (`decide`, `review-change`, `ship`,
`testing-craft`) are byte-identical to the Claude plugin's copies, which
`just sync-check` enforces and fails on -- so the Claude suite covers
them on every platform transitively. Only text that is genuinely
platform-specific diverges: `frame`, `plan` and `review`, plus each
port's own reviewer briefs, each for a reason recorded in that port's
README.

Divergence is therefore a cost to be argued for, not a default. That is
a stronger discipline than a second suite would impose, because it is
checked mechanically on every pull request rather than by a paid run
somebody has to remember to make.

## Consequences

- A port's readiness is never assessed on eval-case count. The questions
  are whether its hooks are the shared ones, whether its divergent text
  is minimal and argued, and whether its platform behaviour has been
  measured (see the hook-surface write-ups).
- Changing a *shared* skill still owes an eval under §13, run through
  `just eval` against the Claude plugin. Nothing about this decision
  loosens that.
- Changing a *divergent* skill -- `plugins/antigravity/skills/plan`,
  say -- cannot be covered by an eval, and that is the real cost of this
  decision. The mitigation is to keep such text as thin as possible and
  to say in the port's README why each piece of it exists, so a reader
  can audit by inspection what no run will catch.
- `tests/test_evals_graders.py` keeps shape-checking the two real
  suites. A grader that could never pass still fails a pull request.
