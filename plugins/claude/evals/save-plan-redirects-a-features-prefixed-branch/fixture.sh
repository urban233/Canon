#!/usr/bin/env bash
# A branch named "features/<slug>" -- the one shape whose plain
# `.canon/plans/<branch>.md` formula collides with a feature plan of the
# same slug (`.canon/plans/features/<slug>.md`). A feature plan for this
# exact slug already exists, so the eval can tell a silent overwrite from
# a genuine redirect: the feature plan's own content must survive the
# branch plan's approval untouched.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
cat > README.md <<'EOF'
# Widget

A small library for building widgets.
EOF
git add README.md
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m init
git checkout -q -b features/public-permalinks

mkdir -p .canon/plans/features
cat > .canon/plans/features/public-permalinks.md <<'EOF'
---
status: approved
steps:
---

# Public Permalinks

## Why
People need to cite datasets by a link that outlives a reorg.

## Steps
1. slug-model: a slug column and a uniqueness constraint
2. resolver: a route that resolves a slug to its dataset
EOF
git add .canon/plans/features/public-permalinks.md
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "feature plan: public permalinks"

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
