---
name: frame
description: Surface the open questions before planning a multi-branch feature, and shape the feature plan mode drafts. Use before entering plan mode for work that obviously won't fit in one branch and one pull request -- never for a change that already does.
---

# Frame

This runs once, before any branch exists for the feature. Framing decides
what's worth building and what shape it takes; plan mode decides how one
piece gets done. The branch is the line between them.

## Ask only what's still open

A competent engineer would want to know: who has this problem, what
changes for them, what does success look like, what's explicitly out of
scope, and the shape at feature altitude -- the data model, the API
surface, not implementation detail. If the opening request already
answers some of these, don't re-ask them. Cover whatever's still open in
one combined question, not one per item.

## What the draft should contain

Before calling `ExitPlanMode`, make sure the plan states:

- `# <Feature name>` as its title -- this becomes the saved plan's
  filename.
- `## Why`, `## Success`, and `## Non-goals` -- the same discipline
  `plan` asks for at branch altitude, one level up.
- `## Shape` -- the technical approach -- and `## Decisions`, only
  where something was genuinely contested (an alternative seriously
  considered, not just the obviously correct way of doing it).
- `## Steps` -- an ordered list, each entry one branch-sized piece: one
  branch, one pull request. A non-empty `## Steps` section is what
  makes the saving hook recognize and save this as a feature plan
  rather than an ordinary branch plan.

  **Lead each step with its branch slug**, then a colon:

  ```markdown
  ## Steps

  - slugs: make duplicate slugs raise, with a regression test
  - permalinks-api: expose the permalink endpoint
  ```

  That slug is how `canon_position` answers "which step am I on" -- it
  matches the slug against branches that exist and pull requests that
  merged. A branch may carry a prefix (`feature/slugs` matches the step
  `slugs`), but a step written without a slug can never be matched to
  anything, and `canon_position` will report it as `unmatched` rather
  than guess. Matching step prose against branch names is exactly the
  wrong-but-plausible inference Canon refuses to make.

## No gate, no new artifact

Nothing here is accepted or advanced through a status. The feature plan
is a document the developer reads, edits, and reorders like any other
file in the repo -- there's no separate design doc, no brief, no launch
plan. When work starts on step one, use the `plan` skill as usual; it
already asks for the parent feature plan when one exists.
