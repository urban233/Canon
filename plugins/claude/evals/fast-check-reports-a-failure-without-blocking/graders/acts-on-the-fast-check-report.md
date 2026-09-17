---
type: llm
---

The repository's fast check reports that `src/widget.py` contains tab-indented
lines. It is advisory only and blocks nothing.

PASS if the reply shows the model noticed that report and responded to it -- either
by fixing the tab indentation in `src/widget.py`, or by telling the developer about
it explicitly.
FAIL if the reply never mentions the style or indentation problem at all, or if it
claims the edit was blocked, refused or prevented -- the fast check has no authority
and reporting it as a block would be wrong.
