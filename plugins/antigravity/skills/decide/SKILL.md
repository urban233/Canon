---
name: decide
description: Draft and commit a decision record for a design or architecture choice made in this session, once it has survived implementation. Use at ship time, right before opening the pull request, when the branch made a decision worth recording.
---

# Decide

## Does this decision earn a record?

Both of these must be true:

- An alternative was seriously considered -- not just the obviously
  correct way of doing something.
- The consequence outlives this branch.

If either half is false, there's nothing to record -- the choice just
happened, it wasn't decided.

## When

At ship time, once the decision has survived contact with the
implementation -- never when it was first proposed. A decision that
got reversed during implementation or review never becomes a record;
it was a draft opinion, not something to archive.

If the branch's plan, or its parent feature plan, already carries a
`## Decisions` entry for this, promote that one rather than treating it
as new.

## What to write

Pick the next number: list `docs/decisions/` for the highest
`NNNN-*.md` prefix and add one, zero-padded to four digits (`0001` if
the directory doesn't exist yet). Slug the title in kebab-case.

Write `docs/decisions/NNNN-slug.md` in the familiar Nygard shape:

```markdown
# NNNN. <Title>

## Context

What prompted this decision -- the problem, the constraint, the forces
in tension.

## Decision

What was chosen, stated plainly.

## Consequences

What this makes easier, what it makes harder, and what it forecloses.
Include the rejected alternative and why it lost -- that's the part a
transcript loses and a repository keeps.
```

No `Status:` field, and no supersession mechanism. If a later decision
reverses this one, the new record says so in its own `## Context` with
a plain reference back to this file; this file is never edited.

## Committing it

Write the file; don't commit it separately. It rides inside whatever
commit the branch already makes next, the same way a saved plan does --
Canon never authors a commit of its own.
