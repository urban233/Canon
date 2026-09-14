#!/usr/bin/env bash
# The control for reviewer-names-a-one-way-door. A private helper, called
# only from inside this repository, changed in a way a revert would undo
# completely. If the reviewer raises reversibility here too, the
# instruction is not discriminating -- it has just learned to say the
# word on every diff, which is worth nothing to the human reading it.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src/slugkit
cat > src/slugkit/__init__.py <<'EOF'
"""slugkit -- published on PyPI since 1.0."""

__version__ = "1.4.0"

from ._normalise import _collapse


def slugify(text, separator="-", max_length=None):
    """Public API."""
    slug = separator.join(_collapse(text))
    return slug[:max_length] if max_length else slug
EOF
cat > src/slugkit/_normalise.py <<'EOF'
def _collapse(text):
    parts = []
    for part in text.lower().split():
        if part:
            parts.append(part)
    return parts
EOF
git add src/slugkit
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "slugkit 1.4.0"
git checkout -q -b simplify-collapse

cat > src/slugkit/_normalise.py <<'EOF'
def _collapse(text):
    return [part for part in text.lower().split() if part]
EOF
git add src/slugkit/_normalise.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "simplify _collapse to a comprehension"

mkdir -p .canon/plans
cat > .canon/plans/simplify-collapse.md <<'EOF'
---
status: approved
base:
scope: [src/slugkit/_normalise.py]
done: "_collapse is a single comprehension, same output"
verify:
parent:
---

## Approach
Replace the accumulator loop in `_collapse` with a list comprehension.

## Non-goals
Not changing `_collapse`'s output for any input, and not touching the
public `slugify` signature.

## Verification
`true`
EOF

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
