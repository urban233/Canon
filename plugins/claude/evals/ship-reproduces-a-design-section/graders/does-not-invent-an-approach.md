---
type: llm
---

The plan states its approach under `## Design`; it has no `## Approach` section.

PASS if the pull request body the reply writes (or drafts, if GitHub could not be
reached) reproduces the plan's `## Design` text and its `## Non-goals` text, and does
not present an `## Approach` section the plan does not have.
FAIL if the body invents or paraphrases an approach under a heading the plan does not
use, omits the design text, or if the reply refuses to ship because `## Approach` is
missing.
