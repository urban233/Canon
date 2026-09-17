#!/usr/bin/env bash
# A branch mid-repair: the reviewer already returned CHANGES REQUIRED
# against an earlier commit, the fix has since landed, and HEAD has moved
# -- so `canon_review` reports that verdict as stale and carries the
# commit it was made against.
#
# The fix itself is the point. It closes the reported finding (the empty
# name case) and quietly breaks something the reviewer had already
# passed: `greet` no longer handles a name that is merely falsy-adjacent,
# and the trailing exclamation mark the earlier commit added is gone. Re-
# reading the whole diff makes that look like part of the change; reading
# the delta against the commit already reviewed is what exposes it.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src
cat > src/greeting.py <<'EOF'
def greet(name):
    return "Hello, " + name
EOF
git add src/greeting.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m init
git checkout -q -b feature/greeting-punctuation

# The commit the reviewer actually looked at.
cat > src/greeting.py <<'EOF'
def greet(name):
    return "Hello, " + name + "!"
EOF
git add src/greeting.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "add exclamation mark to greeting"
reviewed_sha=$(git rev-parse HEAD | cut -c1-9)

# The fix for the reported finding, which also drops the exclamation mark
# the reviewed commit had added.
cat > src/greeting.py <<'EOF'
def greet(name):
    if not name:
        raise ValueError("name is required")
    return "Hello, " + name
EOF
git add src/greeting.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "raise on an empty name"

mkdir -p .canon/plans/feature .canon/hooks
cat > .canon/plans/feature/greeting-punctuation.md <<'EOF'
---
status: approved
base:
scope: [src/greeting.py]
done: "greet() ends with an exclamation mark and rejects an empty name"
verify:
parent:
---

## Approach
Append an exclamation mark to the greeting string, and reject an empty name.

## Non-goals
Not changing greet()'s signature or adding a punctuation parameter.

## Verification
`true`
EOF

cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF

cat > .canon/hooks/decisions.jsonl <<EOF
{"hook": "reviewer", "decision": "CHANGES REQUIRED", "reason": "greet() accepts an empty name and produces a greeting addressed to nobody", "head": "${reviewed_sha}", "timestamp": "2026-01-01T00:00:00Z"}
EOF
