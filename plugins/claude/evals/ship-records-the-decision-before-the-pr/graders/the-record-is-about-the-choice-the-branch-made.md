---
type: llm
---

The branch chose to sign the session into the cookie, having seriously
considered and rejected a Redis-backed server-side session table. The
consequence it accepted is that a session cannot be revoked before it
expires.

PASS if the reply reports that a decision record was written, and shows
it is about that choice -- naming the rejected server-side or Redis
store, or the revocation consequence, in any wording. Opening the pull
request as well is expected and does not affect this grader.
FAIL if the reply never mentions recording a decision, if it says the
branch made no decision worth recording, or if what it describes
recording is some other choice with no connection to the session store.
