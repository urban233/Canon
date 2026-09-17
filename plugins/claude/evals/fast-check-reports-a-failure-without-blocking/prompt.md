---
max_turns: 10
timeout_seconds: 240
# `Write` is deliberately not granted: the grader below asserts an `Edit`
# call, and a model that rewrote the file wholesale would fail a check
# meant only to confirm the edit happened.
allowed_tools: [Read, Glob, Grep, Edit]
---

Please add a `subtract` function to `src/widget.py`, alongside the existing `add`.
