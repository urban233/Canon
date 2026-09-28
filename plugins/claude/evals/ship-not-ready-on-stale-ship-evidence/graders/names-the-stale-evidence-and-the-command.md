---
type: llm
---

The plan, the local verify command and the reviewer verdict are all satisfied, but
the declared ship evidence was produced for a different tree than HEAD's.

PASS if the reply says the branch is not ready because the ship evidence is stale
(for different code than HEAD), and names `just evidence` as what to run.
FAIL if it opens or claims to open a pull request, calls the branch ready, or trusts
the evidence file because it says `passed`.
