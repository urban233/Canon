---
type: regex
target: files
# `target: files` is the newline-separated list of paths CREATED during
# the run, so this can only pass if the model actually wrote the record.
# It is deliberately not a `target: trace` match on `docs/decisions/`:
# `decide/SKILL.md` contains that string itself, so a trace pattern would
# go green the moment the skill was opened, whether or not anything was
# written. That exact false positive is what made
# `frame-states-step-dependencies` unfalsifiable (issue #44).
#
# 0002 rather than any number: the fixture ships 0001, so this also
# asserts `decide`'s "pick the next number" rule.
pattern: '^docs/decisions/0002-[a-z0-9-]+\.md$'
flags: m
---
