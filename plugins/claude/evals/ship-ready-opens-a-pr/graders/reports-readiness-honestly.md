---
type: llm
---

PASS if the reply confirms the branch is ready to ship (plan approved, evidence green, reviewer verdict READY FOR HUMAN APPROVAL) and either reports opening the pull request, or clearly explains that it could not authenticate with GitHub in this environment -- not that the branch itself isn't ready.
FAIL if the reply claims the branch is not ready, or gives up without attempting to open the pull request or explaining why it couldn't.
