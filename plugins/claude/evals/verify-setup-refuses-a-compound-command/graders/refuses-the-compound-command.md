---
type: llm
---

The agent found that this repository's real verification check, documented in CONTRIBUTING.md, is the compound command `ruff check . && pytest`.

PASS if the reply says it cannot save that command as-is because Canon runs the verify command directly with no shell, or otherwise clearly declines to write `ruff check . && pytest` (or an equivalent chained command) into `.canon/config.json` as a single compound `verify` value.
FAIL if the reply treats the compound command as an acceptable answer and reports (or implies) that `.canon/config.json` now contains `"verify": "ruff check . && pytest"` or an equivalent chained command, with no qualification.
