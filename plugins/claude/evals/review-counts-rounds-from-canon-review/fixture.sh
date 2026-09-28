#!/usr/bin/env bash
# Two CHANGES REQUIRED rounds on this branch are already in the log, but
# the prompt says nothing about them: the conversation that held the
# count was compacted away. The count is only available from
# `canon_review`'s `rounds`. Before `rounds` existed the skill said "after
# a compaction the count is gone" -- this case measures that it no
# longer is.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src
cat > src/parser.py <<'EOF'
def parse(text):
    return text.split(",")
EOF
git add src/parser.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "init"
git checkout -q -b feature/parser-hardening
first_sha=$(git rev-parse HEAD | cut -c1-9)
cat > src/parser.py <<'EOF'
def parse(text):
    if text is None:
        raise ValueError("text is required")
    return [part.strip() for part in text.split(",")]
EOF
git add src/parser.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "reject None and strip whitespace"
reviewed_sha=$(git rev-parse HEAD | cut -c1-9)
cat > src/parser.py <<'EOF'
def parse(text):
    if not text:
        raise ValueError("text is required")
    return [part.strip() for part in text.split(",") if part.strip()]
EOF
git add src/parser.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "drop empty fields as well"

mkdir -p .canon/plans/feature .canon/hooks
cat > .canon/plans/feature/parser-hardening.md <<'EOF'
---
status: approved
base:
scope: [src/parser.py]
done: "parse() rejects empty input and returns trimmed, non-empty fields"
verify:
parent:
---

## Approach
Harden parse() against empty input and stray whitespace.

## Non-goals
Not changing parse()'s return type, and not adding a delimiter parameter.

## Verification
`true`
EOF

cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF

cat > .canon/hooks/decisions.jsonl <<EOF
{"hook": "reviewer", "decision": "CHANGES REQUIRED", "reason": "parse() raises AttributeError on None instead of rejecting it", "head": "${first_sha}", "branch": "feature/parser-hardening", "timestamp": "2026-01-01T00:00:00Z"}
{"hook": "reviewer", "decision": "CHANGES REQUIRED", "reason": "parse() still accepts an empty string and returns a list containing one empty field", "head": "${reviewed_sha}", "branch": "feature/parser-hardening", "timestamp": "2026-01-01T01:00:00Z"}
EOF
