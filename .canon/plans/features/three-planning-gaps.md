---
status: approved
steps:
---

# Three planning gaps

Three gaps between what Canon's planning surface promises and what it
does, closed in four branch-sized steps. Each is small, each is
independently shippable, and none adds an artifact, an altitude or a
status.

Found by reading Canon against the public record of how Anthropic
develops with Claude Code, and against the published experience of the
specification frameworks Canon deliberately does not resemble. The
finding that motivates the whole plan is that **Canon already
implements the intent-driven loop correctly** -- plan mode's output
persisted, scope and non-goals derived, review isolated in a fresh
context. These three are the places where a promise in `docs/plan.md`
has no mechanism behind it, or where a mechanism stops one step short
of being useful.

## Why

**Gap 1 -- intent does not survive the handoff it was designed for.**
`save_plan.py` writes the plan into the repository precisely so it
outlives the conversation. But `session_start.py` injects only
`Plan: approved (.canon/plans/<branch>.md)` -- the *status*, never the
intent. A session that compacts, restarts, or is deliberately cleared
is told that intent exists and not what it is, so the next turn
re-reads the file or, worse, proceeds without it. Anthropic's own
guidance makes the fresh session a deliberate step -- "once the spec is
complete, start a fresh session to execute it" -- which only works if
something re-seats the spec. Canon has both halves built and never
connects them.

**Gap 2 -- `## Steps` cannot say what depends on what.** `_steps.py`
reports `current` as "the first step that has not merged", which makes
every feature strictly sequential by construction. Real features are
not. This repository's own `phase-0-2-gap-closure.md` had to draw an
ASCII diagram of a ten-branch stack in prose because the format could
not express it, and that diagram is invisible to `canon_position` --
which went on reporting a single `current` step for a series whose
actual shape was a chain of stacked pull requests. The public guidance
on splitting agentic work turns entirely on independence: work is
parallelisable when units "can operate independently", and sequential
work with many dependencies should not be split at all. Canon cannot
tell the two apart, so it cannot answer "what could I start now".

**Gap 3 -- nothing ever asks whether a change can be taken back out.**
Canon is built on small batches, and small batches exist *for*
revertability. `risk-reviewer.md` asks about "a migration's
reversibility", but `risk-reviewer` is dispatched only on path-matched
auth, data and migration surfaces -- and `review.py` documents,
correctly, why public API surface and destructive operations were left
out of that path matcher: they "need diff-*content* analysis to mean
anything precise". The ordinary `reviewer` does read diff content, and
never asks the question. So a change that alters a published signature,
deletes data, or fires an external side effect gets no reversibility
scrutiny at all unless its path happens to contain a risk keyword.

## Success

- A session started fresh on a branch with a saved plan is told that
  plan's definition of done and its non-goals, without reading the
  file. Verified by a test asserting the injected context contains
  them, and by an eval that fails when the injection is removed.
- A feature plan can state that two steps are independent, and
  `canon_position` reports both as startable. Verified against a
  fixture plan with a diamond-shaped dependency graph.
- `phase-0-2-gap-closure.md`'s real stack, transcribed into the new
  notation, produces the same answer its prose diagram gave a human.
- A diff that changes a public function signature draws a reversibility
  finding from the ordinary reviewer, and an eval fails when the line
  is removed from `reviewer.md`.
- `just ci` stays green at every step; each step is one branch and one
  pull request.

## Non-goals

- **No feature-flag opinion.** Considered and rejected -- see
  `## Decisions`. Canon cannot know a repository's flag mechanism and
  would invent one, which is the wrong-but-plausible inference Canon
  exists to refuse. Feature flags are also a release concern, on the
  far side of the boundary where Canon hands a pull request to a human
  and stops.
- **No `owner:` on a step.** `docs/plan.md` §06 offers "an owner beside
  each step is enough" as the reason `plan-wave` was dropped, and the
  research turned up no public evidence of any human-to-human handoff
  protocol to ground it. The promise should be withdrawn in a decision
  record, not implemented.
- **No altitude above the feature plan.** No roadmap, no backlog, no
  portfolio. Two files at two altitudes stays two.
- **No status, gate or acceptance state on the feature plan.**
  `docs/plan.md` §06's tripwire is explicit: a `frame` artifact that
  acquires an acceptance state has started growing back into CoDev.
- **No parallel execution machinery.** Canon *reports* which steps are
  startable. It does not dispatch agents, allocate work, or create
  worktrees. The developer decides what to do with the answer.
- **No new risk-surface path detection.** `review.py` already argues
  that a path-only heuristic for public API and destructive operations
  is too weak to trust. Gap 3 is answered in the reviewer's brief,
  where diff content is available, not in the path matcher.
- **No change to `docs/plan.md`.** It is the specification. Where the
  code should win over the document -- the withdrawn `owner:` promise
  is one -- that argument goes in `docs/decisions/`.
- **No stored state.** Invariant II applies to every step. A step that
  looks like it wants a cache is wrong.

## Shape

Three kinds of work, and the ordering is set by one real dependency
rather than by preference:

1. **Injection** (step 1) -- self-contained, touches only
   `session_start.py`, shares no surface with anything else here.
2. **The step graph** (steps 2 and 3) -- the parser must understand the
   notation before any skill documents it, so step 3 cannot start until
   step 2 lands. This is the only hard edge in the plan.
3. **The reviewer's brief** (step 4) -- self-contained, touches only
   `reviewer.md` and its eval.

Steps 1 and 4 are independent of everything and of each other. Steps 2
and 3 are a chain.

This plan was first written with those dependencies stated here in prose
and nowhere a tool could read them, because the notation that expresses
them did not parse until step 2 landed -- the gap demonstrating itself,
exactly as `phase-0-2-gap-closure.md` did. `## Steps` now carries them
directly, so `canon_position` gives the same answer this paragraph does
rather than reporting a single sequential `current`.

Two steps change instruction text rather than code (`frame/SKILL.md`,
`reviewer.md`). Both are therefore subject to `docs/plan.md` §13's
admission rule -- no instruction line ships without an eval that fails
when you remove it -- so each carries its eval in the same branch.
Steps 1 and 2 are code and are covered by `bazel test`.

## Decisions

**Dependency notation: `(after: slug)`, not a `[P]` marker.** The
parallelism marker popularised by spec-kit says a step *may* run in
parallel but not *with what* or *after what*. This repository's real
case was a stack, where the useful fact is the edge, not the property.
An explicit edge also degrades correctly: a step naming a dependency
that does not exist is reported, where a bare `[P]` cannot be wrong in
a detectable way. Written as `- slug (after: other): description`, with
several dependencies comma-separated.

**A step with no `after:` depends on the step before it.** The
alternative -- treating an unannotated step as independent -- would
silently change the meaning of every feature plan already written,
including this repository's own, and would report steps as startable
that were always meant to be sequential. Parallelism is opt-in, and the
current behaviour is preserved exactly for every existing plan. This is
the same reasoning `_steps.py` already applies to a step with no slug:
degrade to the honest answer, never to a confident wrong one.

**The `/clear` nudge is deferred, not adopted.** Anthropic's guidance
pairs the written spec with starting a fresh session, and the obvious
companion to step 1 is for `save_plan.py` to suggest it in the
`additionalContext` it already emits. It is left out because
`docs/plan.md` §05 is deliberate that Canon "implements in the
developer's own session by default" -- delegating implementation costs
the context the session already has -- and because the nudge is
instruction bytes with no eval behind it. Step 1 makes clearing *safe*;
whether to recommend it is a separate question, and the ablation suite
is where it should be answered.

**What SessionStart injects is capped.** The plan's `done:` is one
line. `## Non-goals` is not, and injecting an unbounded section into
every session start is exactly the instruction bloat Phase 3 spent a
whole pass removing. The injection takes `done:` in full and non-goals
truncated to a small fixed budget, with the plan's path already present
for the rest. `scope:` is deliberately excluded: `check_scope` already
reports a departure at the moment it happens, which is more useful than
a list read at session start.

## Steps

- handoff-plan-context (after: none): inject the saved plan's definition
  of done and its non-goals at session start, not just its status
- steps-dependencies (after: none): parse `(after: ...)` in `## Steps`
  and report every startable step from `canon_position`
- frame-dependency-notation (after: steps-dependencies): document the
  notation in the `frame` skill, with an eval that fails without it
- reviewer-reversibility (after: none): ask the ordinary reviewer
  whether the change can be taken back out, with an eval that fails
  without it

### 1 · handoff-plan-context

**Change.** `session_start.py`'s `_plan_status` returns a status
string; the message reads `Plan: approved (.canon/plans/<branch>.md).`
Read the saved plan properly instead -- `_common.plan_sections` is
already imported there for `## Open questions` -- and append the
`done:` header field and a truncated `## Non-goals`.

**Why it is safe.** This hook already degrades piece by piece: a
missing plan, a failed git command or an unauthenticated `gh` each drop
only their own fragment. The new fragments follow the same rule, and a
plan with neither field injects exactly what it injects today.

**Verification.** `bazel test //tests:test_claude_hooks_session_start`
with cases for: both fields present; `done:` present and non-goals
absent; neither present (byte-identical to current output); a non-goals
section longer than the budget; a plan file that is not parseable.

**Non-goals for this step.** No change to the compaction recap, which
already carries `## Open questions` and is a different code path. No
`/clear` nudge in `save_plan.py`.

### 2 · steps-dependencies

**Change.** `_steps.py` gains dependency parsing and a startable
computation:

- `parse_steps` recognises `- slug (after: a, b): description` and
  records `depends_on: ["a", "b"]`. A step with no `after:` gets an
  implicit dependency on the preceding step's slug.
- `annotate` marks a dependency naming an unknown slug, rather than
  dropping it -- the same treatment a slugless step already gets.
- `summarize` gains `startable`: every step not merged and not open
  whose dependencies have all merged. `current` keeps its present
  meaning, so `position.py` and `ship.py` need no change to keep
  working.
- A cycle is reported, never traversed.

**Verification.** `bazel test //tests:test_canon_mcp_steps` and
`//tests:test_canon_mcp_position`, with fixtures for: a pure chain
(today's behaviour, unchanged); two independent roots; a diamond; an
unknown dependency; a cycle; and `phase-0-2-gap-closure.md`'s real
ten-branch stack transcribed into the notation, asserted to give the
answer its prose diagram gave.

**Non-goals for this step.** No skill or documentation change -- that
is step 3, and it must not land before the parser understands the
notation. No change to what `canon_ship` considers ready.

### 3 · frame-dependency-notation

**Change.** Document `(after: ...)` in `plugins/claude/skills/frame/SKILL.md`,
beside the existing paragraph explaining why each step leads with its
branch slug. Three or four lines: the syntax, the default, and the one
piece of craft -- **claim independence only where it is true**, because
a step wrongly marked independent is started against a base that does
not have its prerequisite in it, which is a merge conflict at best.

**Verification.** A `claude plugin eval` case: a `frame` prompt for a
feature with two genuinely independent pieces and one dependent piece,
graded on whether the drafted `## Steps` carries the dependency. The
eval must fail with the lines removed -- that is the admission test,
and if it passes without them the lines do not ship.

**Non-goals for this step.** No change to `plan/SKILL.md`; branch
plans link upward with `parent:` and are unaffected. No eval-suite
restructuring.

### 4 · reviewer-reversibility

**Change.** Add the reversibility question to
`plugins/claude/agents/reviewer.md` -- the *ordinary* reviewer, which
sees every change and reads diff content. Roughly: if this change
cannot be cleanly reverted, say so and say why. The one-way doors are
destroyed data, a published interface other code already calls, and an
external side effect. A finding here is informational unless the plan's
`## Non-goals` shows the author already considered it.

**Why here and not in the path matcher.** `review.py` argues that
path-only detection of public API and destructive operations is too
weak to trust, and that argument stands. The reviewer has the diff, so
it can answer what a path cannot.

**Verification.** A `claude plugin eval` case with a diff that changes
a public function signature, graded on whether the verdict names the
reversibility consequence; and a control case with a purely internal
change, graded on the reviewer *not* raising it -- so the line cannot
pass by making the reviewer raise it on everything. Must fail with the
line removed.

**Non-goals for this step.** No change to `risk-reviewer.md`, which
already covers migration reversibility for the surfaces it is
dispatched on. No new dispatch rule and no change to
`_matches_risk_surface`.

## Open questions

- Should `canon_position`'s one-sentence answer change when more than
  one step is startable, or should `startable` stay in the structured
  payload only? Leaning toward the payload alone: the sentence is read
  by a human every session, and "three steps are startable" is a
  different kind of claim from "you are on step four".
- Does step 4's control case need a third variant -- a change that is
  irreversible *and* acknowledged in `## Non-goals` -- to prove the
  reviewer stays quiet when the author already decided? Probably yes,
  but it is cheap to add after the first two run.
