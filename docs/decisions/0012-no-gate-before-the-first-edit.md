# 0012. No gate before the first edit

## Context

Invariant I is "the plan is in the repo before the first edit", and §07's
spine table enforced it with `plan_gate.py`, a `PreToolUse` hook on every
edit and shell command. It did four things: it refused an edit with no
saved plan, refused an edit or a commit on the default branch, and
refused `git switch -c`/`git checkout -b` from any branch other than the
default ("adopt it rather than nest under it").

The decisions log from one field repository
(`open-protein-platform`, 2026-09-22 to 2026-09-28) records what the
gate actually did there: 25 refusals, and not one of them prevented a
mistake.

- **14 "no plan is saved" refusals.** Most were caused by the plan-save
  hook, which never wrote an approved plan on Claude Code until 0.2.1.
  An approved plan existed every time; the gate could not see it.
- **11 "adopt it rather than nest" refusals, one for every stacked
  step created.** Each step of the feature was deliberately cut from
  the step before it. That is the case §12 names as "the one legitimate
  exception", and the gate refused it every time.
- **0 default-branch refusals.**

A gate that refuses the intended workflow every time teaches the agent,
and the developer, to route around it. The field session ended with a
standing permission to write plan files by hand.

## Decision

**`plan_gate.py` is removed, with all four of its checks, on every
platform.** Its now-unused config key `guard_default_branch`, and the
hooks-side `interaction_mode` that only it read, go with it. So does its
eval case, `plan-gate-blocks-an-edit-with-no-plan`.

The plan still matters and is still required. It is just required where
it is read, not before the first keystroke:

- **`canon_ship` still refuses a branch with no approved plan**, and
  still refuses one missing `## Non-goals` or `## Verification` (ADR
  0002). Intent must be recorded before a change is presented as ready.
- **The plan is still saved the moment it is approved**, by
  `save_plan.py`, and read by the scope check, the reviewers and
  `canon_position` as before.

What goes away is refusing to start. The work is not unguarded: the git
guard still refuses the operations that damage the default branch (ADR
0011), GitHub branch protection remains the real gate on `main`, as §12
recommends, and the reviewers still read every change.

## Alternatives rejected

- **Keep the default-branch guard and drop only the plan and nesting
  checks.** This was offered and declined. The guard never fired in the
  field, and an edit on the default branch cannot reach anyone without a
  push or a merge, both of which the git guard and branch protection
  already cover.
- **Keep the plan check but trust the 0.2.1 plan-save fix to make it
  quiet.** That would remove 14 of the 25 refusals and none of the 11
  that blocked stacking, and it keeps a pre-edit gate whose only job
  `canon_ship` already does at the point where it matters.

## Consequences

- **Invariant I is no longer enforced before the first edit.** It is
  enforced at ship time. §04, §07's spine table, §09's `solo` row
  ("ask only at real gates: missing plan, ...") and §12's branch-problem
  section all still describe the gate. The plan document is not edited;
  this record is where that reader lands.
- **An agent can now edit on the default branch.** Nothing it does
  there can leave the machine without a push to the default branch,
  which branch protection governs, or a merge, which the git guard
  refuses.
- **`guard_default_branch` in an existing `.canon/config.json` is now
  ignored.** It is harmless, and it can be deleted.
