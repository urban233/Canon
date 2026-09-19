---
name: ship
description: Decide whether a change is ready to hand to a human, and open the pull request when it is. Use once the work is done and verified, before opening a PR or telling the developer the change is ready.
---

# Ship

1. Call `canon_ship`. Its three checks -- plan satisfied, evidence green
   at this HEAD, independent reviewer verdict present -- are the only
   things that make a change ready.
2. If `ready` is false, stop. Work through `missing` in order rather
   than opening a pull request that isn't actually ready.
3. Before opening the pull request, consider whether this branch made a
   decision worth recording: use the `decide` skill's test (a real
   alternative seriously considered, and a consequence that outlives
   this branch). If it passes, run `decide` first, so the record lands
   in the same commit as the work. This is never a gate -- it's
   imposed on you, not on the developer, and never blocks shipping.
4. If `ready` is true, open the pull request (`gh pr create` via
   `run_command`). The body reproduces the plan's `## Approach` and
   `## Non-goals` sections verbatim and states the exact command
   `canon_evidence` reports as green -- not a summary of the diff, which
   the diff already is. Title: short, present tense, matching the plan's
   `done:` header field when one is set.
5. Never merge or close the pull request, and never approve it -- a
   human does that. This skill's job ends at "opened, ready, and here
   is the evidence."
