#!/usr/bin/env bash
# A real diff, but no saved plan at all -- no acceptance criteria, no
# Non-goals, nothing to check the change against. reviewer.md's own
# instruction is to return BLOCKED BY MISSING EVIDENCE rather than
# reconstruct intent from chat.
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

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
