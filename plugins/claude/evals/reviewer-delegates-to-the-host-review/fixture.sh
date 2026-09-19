#!/usr/bin/env bash
# A diff with one unmistakable correctness defect, and a plan that does
# not excuse it. reviewer.md's instruction is to take its findings from
# Claude Code's built-in review, run as a subprocess -- not to read the
# diff and judge it unaided. This case fails if the reviewer reverts to
# reviewing by hand, which is what the brief used to tell it to do.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src
cat > src/stats.py <<'EOF'
def average(values):
    """The arithmetic mean of `values`."""
    return sum(values) / len(values)
EOF
git add src/stats.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "stats: arithmetic mean"
git checkout -q -b speed-up-average

cat > src/stats.py <<'EOF'
def average(values):
    """The arithmetic mean of `values`."""
    return sum(values[:-1]) / len(values)
EOF
git add src/stats.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "stats: skip the final element"

mkdir -p .canon/plans
cat > .canon/plans/speed-up-average.md <<'EOF'
---
status: approved
base:
scope: [src/**]
done: "average() is faster on large inputs"
verify:
parent:
---

## Approach
Reduce the work `average` does per call.

## Non-goals
Not changing what `average` returns for any input.

## Verification
`true`
EOF

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
