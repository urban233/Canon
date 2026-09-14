#!/usr/bin/env bash
# A plain repo with no docs/decisions/ yet -- numbering should start at
# 0001, and the file should never be committed by the agent itself.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m init
git checkout -q -b feature/storage-format

mkdir -p .canon/plans/feature
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF

# decide is invoked at ship time, when a plan is already approved --
# plan_gate.py would otherwise (correctly) block the Write for the
# decision record itself, since it's still an edit with no plan on a
# branch that hasn't got one yet.
cat > .canon/plans/feature/storage-format.md <<'EOF'
---
status: approved
base:
scope: [src/**]
done: "per-user preferences are stored and readable"
verify:
parent:
---

## Approach
Store per-user preferences as a flat JSON file next to the user's account record.

## Non-goals
Not building a generic preferences framework for other entities.

## Verification
`true`
EOF
