#!/usr/bin/env bash
# A behavior-tested package with an explicitly approved, bounded style plan.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main

mkdir -p pkg tests
cat > pyproject.toml <<'EOF'
[project]
name = "style-remediation-fixture"
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


def build_report(rows):
    """Summarize rows into a totals report.

    Args:
        rows: The data rows to summarize.
    """
    total = 0; count = 0
    for row in rows:
        total += row["amount"]
        count += 1
    return {"total": total, "count": count, "average": _computeAverage(total, count)}


def _computeAverage(total, count):
    return total / count if count else 0.0
EOF

cat > tests/test_reporter.py <<'EOF'
"""Behavior regression tests for the report package."""

import unittest

from pkg import reporter


class ReporterTests(unittest.TestCase):
    """Protect the public report behavior during style remediation."""

    def test_build_report(self):
        """Keep totals, counts, and averages unchanged."""
        report = reporter.build_report([{"amount": 2}, {"amount": 4}])
        self.assertEqual(
            report,
            {"total": 6, "count": 2, "average": 3.0},
        )


if __name__ == "__main__":
    unittest.main()
EOF

git add pyproject.toml pkg tests
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m init
