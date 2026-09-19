---
type: llm
---

The prompt describes three pieces: a search index over `src/blog/storage`, a
`/search` endpoint that queries that index, and a results page in
`src/blog/web`, which both the prompt and the repository's own
`src/blog/web/mocks/` say can be built and reviewed against a signed-off
static mock before the endpoint exists. What is judged is the dependency
shape of the drafted `## Steps` list, not how many steps it has or what they
are called. In that notation an unannotated step waits for the step above it,
and a step listed first waits for nothing.

PASS if the plan states that shape rather than a plain chain: the endpoint
depends on the index -- annotated `(after: <index step>)`, or listed directly
below it, which means the same -- and the results page does not depend on the
endpoint, written `(after: none)`, listed first, or annotated as depending
only on something it genuinely needs, such as a shared layout step. A
different split, or extra steps, is fine as long as those two relationships
hold for whichever steps play those roles.
FAIL if no `## Steps` list was drafted at all -- a reply that only asks
clarifying questions, however sensible, fails -- or if every step is left to
depend on the one before it, or the results page is made to wait on the
endpoint, whether by annotation or by being listed directly below it, or the
index is made to wait on anything.
