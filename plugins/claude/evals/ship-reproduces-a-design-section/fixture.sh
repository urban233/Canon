#!/usr/bin/env bash
# Ready to ship, but the plan states its approach under `## Design`, not
# `## Approach` -- plan mode names that section differently from plan to
# plan, and the plan skill never asks for `## Approach`. The ship skill
# used to demand `## Approach` verbatim; the PR body must reproduce the
# section the plan actually has, and must not invent one.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m "init"
git checkout -q -b feature/widget
git remote add origin https://example.invalid/eval/repo.git
mkdir -p src
cat > src/widget.py <<'EOF'
def render_widget(name):
    return f"<div class=\"widget\">{name}</div>"
EOF
git add src/widget.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "implement the widget component"

mkdir -p .canon/plans/feature .canon/hooks
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
cat > .canon/plans/feature/widget.md <<'EOF'
---
status: approved
base:
scope: [src/**]
done: "the widget renders correctly"
verify:
parent:
---

## Design
Render the widget as one div whose class is fixed at "widget", with the name escaped by the template layer.

## Non-goals
Not touching the gadget module -- that is a separate piece of work.

## Verification
`true`
EOF
head_sha=$(git rev-parse HEAD | cut -c1-9)
cat > .canon/hooks/decisions.jsonl <<EOF
{"hook": "reviewer", "decision": "READY FOR HUMAN APPROVAL", "reason": "looks good, ship it", "head": "${head_sha}", "branch": "feature/widget", "timestamp": "2026-01-01T00:00:00Z"}
EOF
