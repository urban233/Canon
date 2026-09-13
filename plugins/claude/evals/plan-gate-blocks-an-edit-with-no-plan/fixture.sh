#!/usr/bin/env bash
# A feature branch (not the default branch) with Canon active, a real
# typo to fix, and no saved plan -- plan_gate should ask before the
# first edit rather than let it through silently.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
cat > README.md <<'EOF'
# Widget

This library lets you recieve widget events and act on them.
EOF
git add README.md
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m init
git checkout -q -b feature/fix-typo

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
