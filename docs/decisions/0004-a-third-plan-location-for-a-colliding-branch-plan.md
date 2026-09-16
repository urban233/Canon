# 0004. A third plan location, for a branch under the reserved "features/" prefix

## Context

§06 describes exactly two places a saved plan lives: `.canon/plans/<branch>.md`
for a branch plan, `.canon/plans/features/<slug>.md` for a feature plan. Those
two formulas collide whenever `branch` itself starts with `features/` — a
branch named `features/public-permalinks` reduces, via the plain
`<branch>.md` formula, to `.canon/plans/features/public-permalinks.md`, the
identical path a feature plan titled "Public Permalinks" uses. Nothing in
`branch_plan_path` or `feature_plan_path` ever considered that this one
prefix is reserved. Writing a branch plan there silently overwrites the
feature plan, or is silently overwritten by one saved later — the developer's
only warning is a diff they would have to notice, on the one artifact Canon
persists into the repository at all.

Two fixes were on the table. Refuse to write the branch plan and say why, or
write it somewhere else and say so. Refusing keeps the on-disk contract to
exactly the two locations §06 describes, at the cost of the branch never
getting the one persisted artifact this mechanism exists to give it — for a
branch that may have nothing to do with any feature plan, purely because of a
naming coincidence. That reopens the `~/.claude/plans/` gap (unreviewable in
a PR, unreadable by a hook, swept after 30 days) that is §06's entire reason
to exist, for exactly the developer least likely to expect it: one who
happened to name a branch starting with `features/`.

## Decision

Redirect, and say so once. A branch under the reserved `features/` prefix
writes its plan to `.canon/plans/branches/<branch>.md` instead — a third,
narrower location, used only for this one case — and
`branch_namespace_collision_message` names the redirect in the same
one-time, never-blocking voice as `missing_sections_message` ("The plan
itself is saved either way; Canon mentions this once").

A sibling directory, not a same-directory suffix. An earlier version of this
fix redirected to `.canon/plans/features/<branch>.branch.md` — same
directory, different filename. That is wrong specifically on Codex: the
`normalize_plan.py` hook dispatches a touched path by directory prefix, so a
file still nested under `.canon/plans/features/` is routed back through the
feature-plan branch on every *subsequent* edit, re-deriving the branch name
by stripping only `.md` — which leaves a `.branch` fragment stuck to the end
(`features/x.branch` instead of `features/x`), corrupting it a little more
on each pass. `.canon/plans/branches/` sits outside `.canon/plans/features/`
entirely, so once a file is relocated there, every later edit to it is
dispatched by a stable, unambiguous prefix.

The reserved-prefix check (`branch_plan_collides_with_feature_namespace`) is
a prefix check on the branch name, not an existing-file check, and it
compares case-insensitively. Both are conservative in the same direction: a
branch written under `features/` today collides just as fatally with a
feature plan saved under it tomorrow as with one that already exists, and
`.canon/plans/Features/<x>.md` is the same file as
`.canon/plans/features/<x>.md` on the case-insensitive filesystems both of
Canon's supported development platforms (macOS, Windows) default to. Either
comparison being narrower would let exactly the filesystem collision this
decision exists to prevent through undetected.

## Consequences

`.canon/plans/branches/` is now reserved too, alongside `.canon/plans/` and
`.canon/plans/features/` — a fact this record exists to carry, since §06
itself still only describes two locations and is not edited to match it (the
plan document is the specification; where code needs to diverge from it,
that argument belongs here, not in an edit to §06).

One further overlap is accepted rather than solved: a branch genuinely named
`branches/features/<x>` reduces to the identical path this redirect sends a
`features/<x>` branch to. Not solvable without a sentinel of its own, and a
far smaller hole than the one this decision replaces — `features/` is a
convention teams reach for without thinking (a feature branch, named after
the thing it builds); `branches/features/` is not.

The read side does not yet know about the third location. `check_scope.py`,
`plan_gate.py`, and `canon_mcp`'s `_config.py`/`position.py`/`plan.py`/
`ship.py` all still build a branch's plan path as the literal
`.canon/plans/<branch>.md` — for a `features/x` branch, they now find nothing
there (if no same-slug feature plan exists) rather than silently reading the
wrong document, which is an improvement, but they remain unable to see the
plan this decision actually saves. Tracked as a follow-up (issue #54), not
folded into the write-side fix this record documents.
