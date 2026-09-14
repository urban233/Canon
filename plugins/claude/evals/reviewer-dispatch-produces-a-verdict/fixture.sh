#!/usr/bin/env bash
# A feature branch with a small real base->head diff and an approved
# plan, so the reviewer subagent has something concrete to read.
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

cat > src/greeting.py <<'EOF'
def greet(name):
    return "Hello, " + name + "!"
EOF
git add src/greeting.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "add exclamation mark to greeting"

mkdir -p .canon/plans/feature
cat > .canon/plans/feature/greeting-punctuation.md <<'EOF'
---
status: approved
base:
scope: [src/greeting.py]
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

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
