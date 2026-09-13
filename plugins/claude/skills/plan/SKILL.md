---
name: plan
description: Shape what plan mode drafts, so the plan Canon saves needs no follow-up. Use whenever drafting a plan for approval in plan mode, before presenting it with ExitPlanMode.
---

# Plan

Canon's `PostToolUse:ExitPlanMode` hook saves an approved plan verbatim
to `.canon/plans/<branch>.md`, with a small header it derives itself
(branch, base commit, the repo's configured verify command). It leaves
`scope`, `done`, and `parent` blank rather than inventing them — filling
those in well is this skill's job, done once, before the plan is
presented for approval, not after.

Before calling `ExitPlanMode`:

1. Make sure the plan states its **scope** (which files or directories
   it will touch), its **definition of done**, and, if this is one step
   of a larger multi-step feature, the **parent** feature plan it
   belongs under. These become the saved plan's header fields.
2. If any of those genuinely aren't obvious from the request or from
   `.canon/config.json`, ask the developer once — a single question
   covering whatever's unclear, not one question per field — before
   finalizing the plan.
3. Always include a `## Non-goals` section and a `## Verification`
   section in the plan body. Both are read back later: `Non-goals` by
   the scope check and a reviewer, `Verification` by the `Stop` hook.
   A plan missing either gets a note about it in the saved header today
   — the point of this skill is that a developer never has to see that
   note in the first place.
