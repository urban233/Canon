# 0002. `canon_ship` blocks on a missing required section

## Context

§06 is explicit that saving a plan is not a gate:

> At save time the hook checks only that the two required ones are
> present and non-empty. Missing → it asks, once. **It never rejects a
> plan.**

The implementation did neither half of that. `save_plan.py` recorded a
`notes:` line in the saved header and emitted nothing, so nobody was ever
told. Meanwhile `canon_ship` read that same `notes:` field and reported
the change as not ready — which is a rejection, just deferred. The
behaviour was inverted from the document at both ends: silent where §06
says ask, blocking where §06 says never reject.

Fixing the first half is uncontroversial and lands in the same change as
this record. The second half is a real choice, because the obvious
symmetric fix — stop blocking at ship too — is defensible and was
seriously considered.

## Decision

`canon_ship` keeps treating a missing `## Non-goals` or `## Verification`
as not-ready, and `save_plan.py` now asks at save time.

The two halves are one decision rather than two, and the order matters:
**the ask is what makes the block fair.** Before this change, `canon_ship`
blocked on a condition nobody had been told about, discovered at the
moment the work was otherwise finished — the worst possible time, and
exactly the kind of late-surfacing gate CoDev's history is full of. After
it, a developer is told at the moment the plan is approved, when adding
the section costs a sentence. A block at ship time is then a block on
something that was surfaced, cheap to fix, and left undone.

§06's "never rejects a plan" is read as governing the plan artifact,
which is what that sentence is about: the plan is saved verbatim, with
its header note, whatever it is missing. Canon does not refuse to record
it, does not demand an edit before proceeding, and does not alter the
body. Shipping is a different gate with different authority — §11's three
quality layers — and `canon_ship`'s whole contract is reporting whether
the three invariants are met, not whether a document is well-formed.

The sections are load-bearing at exactly that moment, which is why this
is not ceremony:

- `## Non-goals` is what tells a reviewer that an omission was deliberate.
  A pull request handed to a human without it invites a review finding
  for work that was never in scope.
- `## Verification` states what counts as done, and since 0001's sibling
  change it is also where a per-branch `verify:` override is written.

## Consequences

A developer who ignores the save-time ask meets it again at ship time,
with the same words, and can fix it in one edit to a file they own. A
developer who answers it never sees it twice.

The rejected alternative — downgrading ship to a warning — loses because
it makes both mentions advisory, and a required section that nothing
enforces is a conventional section with extra words in the documentation.
§06's own rule is that a section is required only if something reads it;
the corollary is that if nothing acts on its absence, it was never
required.

The cost is that §06's sentence, read alone, predicts that Canon never
refuses anything over a missing section, and `canon_ship` does. That
gap is the reason this record exists. The plan document is not edited.
