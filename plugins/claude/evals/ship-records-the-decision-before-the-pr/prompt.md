---
max_turns: 20
timeout_seconds: 420
allowed_tools: [Read, Glob, Grep, Bash, Write, Edit]
---

There's no network in this sandbox, so GitHub is served from a snapshot
by the `gh` wrapper committed at `./bin/gh`. Call it by that path.

This branch's work is done and reviewed. Use the ship skill to check
whether it's ready, and take it through to a pull request if it is.
