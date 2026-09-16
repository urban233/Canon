#!/usr/bin/env bash
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main

mkdir -p pkg
cat > pkg/calculator.py <<'EOF'
"""Small arithmetic helpers."""


def add(left: int, right: int) -> int:
    """Return the sum of two integers."""
    return left + right
EOF

git add pkg
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m init
