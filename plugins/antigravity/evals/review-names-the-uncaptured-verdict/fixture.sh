#!/usr/bin/env bash
# A branch whose reviewer has already reported, on a platform where no
# hook captured that verdict. `canon_review` therefore has nothing
# stored, and the only record is the reviewer's own final message.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m init
git checkout -q -b feature/widget

mkdir -p .canon/plans
cat > .canon/config.json <<'CFG'
{
  "verify": "true"
}
CFG
cat > .canon/plans/feature-widget.md <<'PLAN'
---
scope: "src/widget.py"
done: "Add the widget"
verify: "true"
---

# Add the widget

## Approach

Add one function.

## Non-goals

Nothing else.
PLAN

printf 'def widget():\n    return 1\n' > widget.py
git add -A
git -c user.email=eval@example.com -c user.name="Canon Eval" commit -q -m "add widget"
