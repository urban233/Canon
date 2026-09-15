#!/usr/bin/env bash
# A breaking change to a published interface, on a path that carries no
# risk-surface keyword -- so `risk-reviewer` is not dispatched and the
# ordinary reviewer is the only thing that can notice. That is the exact
# hole this case exists to cover: `review.py` deliberately leaves public
# API surface out of its path matcher because detecting it needs diff
# content, which only a reviewer has.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src/slugkit
cat > src/slugkit/__init__.py <<'EOF'
"""slugkit -- published on PyPI since 1.0. Downstream code imports this."""

__version__ = "1.4.0"


def slugify(text, separator="-", max_length=None):
    """Public API. Called by downstream packages as slugify(t, "_")."""
    parts = [p for p in text.lower().split() if p]
    slug = separator.join(parts)
    return slug[:max_length] if max_length else slug
EOF
git add src/slugkit/__init__.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "slugkit 1.4.0"
git checkout -q -b tidy-slugify-signature

cat > src/slugkit/__init__.py <<'EOF'
"""slugkit -- published on PyPI since 1.0. Downstream code imports this."""

__version__ = "1.4.1"


def slugify(text, *, sep="-", limit=None):
    """Public API."""
    parts = [p for p in text.lower().split() if p]
    slug = sep.join(parts)
    return slug[:limit] if limit else slug
EOF
git add src/slugkit/__init__.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "tidy slugify's keyword arguments"

mkdir -p .canon/plans
cat > .canon/plans/tidy-slugify-signature.md <<'EOF'
---
status: approved
base:
scope: [src/slugkit/**]
done: "slugify's options are keyword-only with clearer names"
verify:
parent:
---

## Approach
Rename `separator` to `sep` and `max_length` to `limit`, and make both
keyword-only.

## Non-goals
Not changing what slugify returns for any input it still accepts.

## Verification
`true`
EOF

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
