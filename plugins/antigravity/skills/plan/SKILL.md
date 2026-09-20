---
name: plan
description: Shape what plan mode drafts, so the plan Canon saves needs no follow-up. Use whenever drafting a plan for approval in plan mode, before writing it to .canon/plans/.
---

# Plan

Antigravity has no `ExitPlanMode` tool, so once the developer approves a
plan drafted in plan mode (`agy --mode plan`, or the IDE's planning
surface), write it yourself, verbatim, to
`.canon/plans/<branch>.md` (or `.canon/plans/features/<slug>.md` if this
is a feature plan, per the `frame` skill). Canon's own `PostToolUse` hook
(`normalize_plan.py`) then rewrites the file's header, derived from the
sections below — it does not trust any header you write yourself, so
don't write one; start the file with the plan's own `# ` title and
sections. The header is read back later by other hooks and by
`canon-mcp`, and **the hook can only derive a field from a section the
plan actually contains.** Seeding those sections while plan mode is
drafting is this skill's whole job — done once, before you write the
file, not after.

Only write the file once the developer has actually approved the plan.
Nothing on this platform confirms that the way an `ExitPlanMode` tool
call does on Claude Code, so treat "write it" as itself a consequential
action: don't write a plan the developer hasn't seen and signed off on,
and don't write partial drafts as you iterate on one with the developer
-- write once, when it's done.

## Sections the header is derived from

Write these with these headings. The hook looks them up by name; a
section it can't find leaves its field blank rather than being invented.

| Section | Becomes | Read by |
|---|---|---|
| `## Scope` | `scope:` | the `PostToolUse` scope check, on every edit |
| `## Done` | `done:` | `canon_ship`, and the pull request title |
| `## Parent` | `parent:` | `canon_plan`, to link a step to its feature plan |

- **`## Scope`** — one path or glob per line, or a comma-separated list.
  Backticks are fine and commentary after the pattern is dropped, so
  ``- `src/slugs/**` — the slug module`` works. A line with no
  path-shaped token in it is ignored entirely: a scope written as prose
  produces no `scope:` at all, because a wrong scope is worse than an
  absent one — every edit outside it is reported as a departure.
- **`## Done`** — one line, the definition of done.
- **`## Parent`** — only when this branch is one step of a feature plan:
  name the branch after that step's slug in the feature plan's
  `## Steps`, or `canon_position` cannot tell which step this is —
  the feature plan's filename (`public-permalinks.md`). It is written to
  the header only if that file exists under `.canon/plans/features/`;
  a name that resolves to nothing is silently left blank, so get it
  right.

`status` and `base` need no section — the hook reads those from git
itself.

## Overriding the verify command, for this branch only

`verify:` is normally left blank, and `.canon/config.json` answers for
the whole repository. Override it only when this branch genuinely needs
a different command — then write that command as the **first line of
`## Verification`, in backticks, on its own**:

```markdown
## Verification

`pytest tests/slugs/ -x`

Confirm the new test fails without the fix.
```

Only that exact shape is recognised. A command described in prose is not
picked up, deliberately: this field decides what gates every turn end on
the branch, and guessing a command out of a sentence is the
wrong-but-plausible failure Canon exists to avoid. Prose after the first
line is fine and is for the human.

Leave it out unless you mean it. A blank `verify:` follows the
repository's config, including later changes to it; a filled one does
not.

## Sections that are required

Always include `## Non-goals` and `## Verification`. Both are read back:
`Non-goals` by the scope check and by a reviewer, `Verification` by the
`Stop` hook. A plan missing either gets a note added as context after
the file is written.

One piece of craft: **a Non-goal is only useful if it was tempting.**
"Don't rewrite the module" earns its line; "don't break anything" is
noise. The test is whether a competent agent, given this plan and no
Non-goals section, would plausibly have done it.

## Ask once, before finalizing

If scope, done, or the parent genuinely aren't obvious from the request
or from `.canon/config.json`, ask the developer **once** — a single
question covering whatever is unclear, not one per field.
