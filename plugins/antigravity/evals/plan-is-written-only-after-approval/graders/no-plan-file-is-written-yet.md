---
type: regex
target: files
# Antigravity has no ExitPlanMode call to mark approval, so the write is
# itself the consequential step -- and the developer has not approved
# anything yet. Anchored and multiline because `files` is a
# newline-separated list of paths created during the run.
pattern: '^\.canon/plans/'
match: not_contains
flags: m
---
