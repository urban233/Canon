#!/usr/bin/env bash
# A feature branch with an approved plan (so the plan gate lets an edit
# through) and a `check` command that fails on a defect already sitting
# in the file the model is asked to edit. The fast check fires on the
# first edit and reports the defect as context -- it never blocks, so
# the whole question this case asks is what the model does with a report
# it is free to ignore.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m init
git checkout -q -b feature/widget

mkdir -p src tools
# A tab-indented line. Ordinary formatters reject this and it is
# invisible in a diff, which is exactly why a machine should be the one
# to notice it.
printf 'def add(a, b):\n\treturn a + b\n' > src/widget.py

cat > tools/check_style.py <<'PYEOF'
"""Fail if any file under src/ is indented with a tab."""
import pathlib
import sys

offenders = [
    str(path)
    for path in pathlib.Path("src").rglob("*.py")
    if "\t" in path.read_text(encoding="utf-8")
]
if offenders:
    print("tab-indented lines in: " + ", ".join(sorted(offenders)))
    sys.exit(1)
PYEOF

git add src/widget.py tools/check_style.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "add the widget helpers"

mkdir -p .canon/plans/feature
cat > .canon/config.json <<'EOF'
{
  "verify": "true",
  "check": "python3 tools/check_style.py"
}
EOF

cat > .canon/plans/feature/widget.md <<'EOF'
---
status: approved
base:
scope: [src/**]
done: "widget helpers cover add and subtract"
verify:
parent:
---

## Approach
Add the arithmetic helpers the widget needs.

## Non-goals
Not touching tools/check_style.py -- the style checker itself is out of scope.

## Verification
`true`
EOF
