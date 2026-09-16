---
max_turns: 12
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Bash, Skill]
---

Run `$audit-google-python-style` for the `pkg/` package. This is the audit and
planning phase only: do not modify source files, do not run write-mode
formatters, and do not apply fixes. Use the bundled supplemental checker and
give me a grouped remediation plan with the exact scope. End exactly with
`APPROVAL REQUIRED`.
