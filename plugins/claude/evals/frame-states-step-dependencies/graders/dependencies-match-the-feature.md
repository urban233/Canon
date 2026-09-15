---
type: llm
---

The prompt describes three pieces: a search index over storage, a `/search`
endpoint that queries that index, and a results page that the prompt says can
be built against a signed-off static mock without the endpoint existing.

PASS if the drafted `## Steps` expresses that shape rather than a plain chain
-- the endpoint waiting on the index, and the results page not waiting on the
endpoint (written either as `(after: none)` or as depending only on something
it genuinely needs).
FAIL if every step is left to depend on the one before it, if the results page
is made to wait on the endpoint, or if the index is made to wait on anything.
