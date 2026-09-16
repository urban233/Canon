#!/usr/bin/env bash
# A small package with deterministic Google Python Style violations. Phase A
# must report them without changing the tracked source.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main

mkdir -p pkg
cat > pyproject.toml <<'EOF'
[project]
name = "style-audit-fixture"
version = "0.1.0"

[tool.ruff]
line-length = 88
EOF

cat > pkg/__init__.py <<'EOF'
"""Report-generation package."""
EOF

cat > pkg/reporter.py <<'EOF'
"""Summarize row data into a small totals report."""

from os.path import *


def build_report(rows, totals=[]):
    """Summarize rows into a totals report.

    Args:
        rows: The data rows to summarize.
    """
    total = 0; count = 0
    for row in rows:
        total += row["amount"]
        count += 1
    totals.append(total)
    return {"total": total, "count": count, "history": totals}


def _compute_average(total, count):
    return total / count if count else 0.0
EOF

git add pyproject.toml pkg
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m init
