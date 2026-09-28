#!/usr/bin/env bash
# The reviewer returned READY FOR HUMAN APPROVAL with one non-blocking
# note; the only commit since closes that note, in docs. HEAD has moved,
# so the verdict is stale and a fresh one is needed -- but everything up
# to the reviewed commit is already passed, so only the delta needs
# reading. In the field, re-reading the whole range after every such fix
# cost a full round (~350k tokens) each time, for no new coverage.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src docs
cat > src/greeting.py <<'EOF'
def greet(name):
    return "Hello, " + name
EOF
printf '# Greeting\n\nCall greet(name).\n' > docs/greeting.md
git add src docs
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "init"
git checkout -q -b feature/greeting-punctuation

cat > src/greeting.py <<'EOF'
def greet(name):
    return "Hello, " + name + "!"
EOF
git add src/greeting.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "add exclamation mark to greeting"
reviewed_sha=$(git rev-parse HEAD | cut -c1-9)

printf '# Greeting\n\nCall greet(name); the greeting ends with "!".\n' > docs/greeting.md
git add docs/greeting.md
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "docs: say the greeting ends with an exclamation mark"
mkdir -p .canon/plans/feature .canon/hooks
cat > .canon/plans/feature/greeting-punctuation.md <<'EOF'
---
status: approved
base:
scope: [src/greeting.py, docs/greeting.md]
done: "greet() ends with an exclamation mark"
verify:
parent:
---

## Approach
Append an exclamation mark to the greeting string.

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
{"hook": "reviewer", "decision": "READY FOR HUMAN APPROVAL", "reason": "Ready, with one non-blocking note: docs/greeting.md should say the greeting now ends with an exclamation mark.", "head": "${reviewed_sha}", "branch": "feature/greeting-punctuation", "timestamp": "2026-01-01T00:00:00Z"}
EOF
