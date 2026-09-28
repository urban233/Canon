#!/usr/bin/env bash
# Everything is ready except the declared ship evidence: its result file
# records a tree that is not HEAD's -- produced before the last commit.
# docs/decisions/0010-ship-evidence-is-verified-not-stored.md: canon_ship
# must report it stale and say what to run, and no PR may be opened on
# evidence for different code. In the field such a file was matched to
# HEAD by timestamp.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m "init"
git checkout -q -b feature/widget
mkdir -p src build
cat > src/widget.py <<'EOF'
def render_widget(name):
    return f"<div>{name}</div>"
EOF
git add src/widget.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "implement the widget component"
old_tree=$(git rev-parse HEAD^{tree})
cat > src/widget.py <<'EOF'
def render_widget(name):
    return f"<div class=\"widget\">{name}</div>"
EOF
git add src/widget.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "add the widget class"
printf 'build/\n.canon/hooks/\n' > .gitignore
cat > build/evidence.json <<EOF
{"tree": "${old_tree}", "dirty": false, "passed": true, "checks": [{"name": "display evidence run", "passed": true}]}
EOF

mkdir -p .canon/plans/feature .canon/hooks
cat > .canon/config.json <<'EOF'
{
  "verify": "true",
  "ship_evidence": {"command": "just evidence", "result": "build/evidence.json"}
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
Implement the widget component.

## Non-goals
Not touching the gadget module.

## Verification
`true`
EOF
head_sha=$(git rev-parse HEAD | cut -c1-9)
cat > .canon/hooks/decisions.jsonl <<EOF
{"hook": "reviewer", "decision": "READY FOR HUMAN APPROVAL", "reason": "looks good", "head": "${head_sha}", "branch": "feature/widget", "timestamp": "2026-01-01T00:00:00Z"}
EOF
