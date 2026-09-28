#!/usr/bin/env bash
# `.canon/config.json` configures the reviewer's model. Both agent
# definitions hard-code `model: opus`, so a dispatch that ignores
# `canon_review`'s `models` silently runs on the wrong one -- in the field
# the user had to say "Sonnet for the general review" mid-session.
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
  "verify": "true",
  "reviewers": {"reviewer": {"model": "sonnet"}}
}
EOF
