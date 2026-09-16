---
max_turns: 20
timeout_seconds: 420
allowed_tools: [Read, Glob, Grep, Bash, Edit, Write, Skill]
---

Run `$audit-google-python-style` in its approved remediation phase. I explicitly
approve this exact plan for `pkg/reporter.py` only:

1. Remove the unused wildcard import.
2. Split the semicolon-joined assignments.
3. Rename private `_computeAverage` to `_compute_average` and update its caller.
4. Complete the `build_report` and `_compute_average` Google-style docstrings.

Do not change configuration, tests, public behavior, or any other file. Run the
bundled supplemental checker against `pkg/` before and after the edit, run
`python3 -m unittest discover -s tests`, and inspect `git diff --name-only` plus
`git diff --check`. Report exact evidence and end exactly with `COMPLETED`.
