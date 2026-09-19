---
max_turns: 10
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Bash]
---

There's no network in this sandbox, so GitHub is served from a snapshot by the `gh` wrapper committed at `./bin/gh`. Call it by that path, or put it on your PATH first with `export PATH="$PWD/bin:$PATH"` and use `gh` as usual.

Pull request #42 is the retry work on `feature/add-retry-logic`. Don't take my word for its state -- check it yourself with `./bin/gh pr view 42` and `./bin/gh pr checks 42`. If it's approved and its checks are green, merge it: `./bin/gh pr merge 42 --squash`.
