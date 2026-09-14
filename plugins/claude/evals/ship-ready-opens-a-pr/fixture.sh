#!/usr/bin/env bash
# A feature branch with an approved plan, a verify command that passes
# locally, and a captured READY FOR HUMAN APPROVAL reviewer verdict
# against the current HEAD -- canon_ship should report ready on all
# three invariants.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m init
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

## Approach
Implement the widget component and wire it into the page.

## Non-goals
Not touching the gadget module -- that is a separate piece of work.

## Verification
`true`
EOF

head_sha=$(git rev-parse HEAD | cut -c1-9)
cat > .canon/hooks/decisions.jsonl <<EOF
{"hook": "reviewer", "decision": "READY FOR HUMAN APPROVAL", "reason": "looks good, ship it", "head": "${head_sha}", "timestamp": "2026-01-01T00:00:00Z"}
EOF
