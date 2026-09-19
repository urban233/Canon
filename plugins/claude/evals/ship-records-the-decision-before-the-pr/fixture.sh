#!/usr/bin/env bash
# A branch that is ready to ship on all three of `canon_ship`'s checks
# AND carries a genuine decide-worthy choice, so `ship` step 3's nudge
# ("consider whether this branch made a decision worth recording") has
# something real to fire on.
#
# The choice is written into the plan's `## Approach` rather than into a
# `## Decisions` entry on purpose: `decide` says an existing entry should
# be *promoted* rather than treated as new, and this case is about the
# skill noticing an unrecorded decision, not about promotion.
#
# It passes both halves of `decide`'s test:
#   - a real alternative was seriously considered (a Redis-backed
#     server-side store), and
#   - the consequence outlives this branch (sessions cannot be revoked
#     mid-flight, forever, for every future caller).
#
# `docs/decisions/0001-*.md` already exists so that `decide`'s "pick the
# next number" rule has a predictable answer -- the grader asserts the
# record lands at 0002, which also tests the numbering rule.
#
# `bin/gh` is an offline snapshot wrapper, committed so the tree stays
# clean. Without it `gh` is unauthenticated in the sandbox and the model
# reasonably declines to open the pull request at all, which is the
# confound that hollowed out `ship-ready-opens-a-pr` (see issue #52 and
# the run of 2026-09-19). It never refuses anything itself.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m init
git checkout -q -b feature/session-store
git remote add origin https://github.com/canon-eval/webapp.git

mkdir -p src docs/decisions bin

cat > src/sessions.py <<'PY'
"""Session issuing and verification.

The session payload travels in the cookie itself, signed; there is no
server-side session table to look it up in.
"""

import base64
import hmac
import json
from hashlib import sha256

_SECRET = b"eval-only-not-a-real-secret"


def _sign(raw: bytes) -> str:
    return hmac.new(_SECRET, raw, sha256).hexdigest()


def issue(user_id: str, issued_at: int) -> str:
    """A signed cookie value carrying the whole session."""
    raw = json.dumps({"user_id": user_id, "issued_at": issued_at}).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{body}.{_sign(raw)}"


def verify(cookie: str) -> dict | None:
    """The session inside `cookie`, or None if the signature is wrong."""
    body, _, signature = cookie.partition(".")
    padding = "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(body + padding)
    except Exception:
        return None
    if not hmac.compare_digest(_sign(raw), signature):
        return None
    return json.loads(raw)
PY

cat > docs/decisions/0001-what-a-request-id-is-for.md <<'MD'
# 0001. A request id is generated at the edge, not per service

## Context

Every service was minting its own correlation id, so a single user
action produced four unrelated ids and no way to join them up.

## Decision

The edge proxy generates one request id and passes it down. Services
read it and never mint their own.

## Consequences

Tracing across services becomes a grep for one id. The cost is that a
service called outside a request context has no id at all, and has to
cope with that rather than inventing one.
MD

cat > bin/gh <<'GH'
#!/usr/bin/env bash
# An offline snapshot of the few `gh` calls this sandbox needs. No
# network, no repo mutation. It never refuses anything -- refusing is
# Canon's job, and a wrapper that refused would hide whether Canon did.
set -euo pipefail

case "$1 ${2:-}" in
  "--version ")
    echo "gh version 2.63.2 (2026-01-05)" ;;
  "auth status")
    cat <<'OUT' >&2
github.com
  ✓ Logged in to github.com account canon-eval (keyring)
  - Active account: true
  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'
OUT
    ;;
  "repo view")
    echo "canon-eval/webapp" ;;
  "pr create")
    echo "https://github.com/canon-eval/webapp/pull/128" ;;
  "pr list")
    echo "" ;;
  "pr status")
    echo "Current branch: no open pull requests" ;;
  *)
    echo "gh: this sandbox's offline snapshot serves only 'auth status', 'repo view' and 'pr create|list|status'; there is no network here" >&2
    exit 1 ;;
esac
GH
chmod +x bin/gh

git add src/sessions.py docs/decisions/0001-what-a-request-id-is-for.md bin/gh
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "sessions: sign the session into the cookie"

mkdir -p .canon/plans/feature .canon/hooks

cat > .canon/config.json <<'JSON'
{
  "verify": "true"
}
JSON

cat > .canon/plans/feature/session-store.md <<'MD'
---
status: approved
base:
scope: [src/**]
done: "a signed session survives a round trip and a tampered one is rejected"
verify:
parent:
---

## Approach

Sign the session payload into the cookie itself, so verifying a request
is an HMAC check and nothing else.

We seriously considered a Redis-backed server-side session table, which
is the more usual shape and was the starting assumption. It lost on
operational cost: it is a second piece of infrastructure to run, back up
and page someone about, and this product has one box. The consequence we
are accepting is that a session cannot be revoked before it expires --
there is nothing server-side to delete -- so logout is best-effort and
every future feature that wants real revocation has to reopen this.

## Non-goals

Not shortening the expiry window to paper over the revocation gap, and
not touching the login form.

## Verification

`true`
MD

head_sha=$(git rev-parse HEAD | cut -c1-9)
# Both reviewers, because `src/sessions.py` matches the `auth` risk
# surface on the substring `session` (see `_RISK_SURFACE_KEYWORDS` in
# canon_mcp/review.py). `canon_ship` waits on every reviewer that was
# called for, so with only the plain `reviewer` verdict here the case
# would never reach step 3 at all -- it would stop at "not ready".
cat > .canon/hooks/decisions.jsonl <<EOF
{"hook": "reviewer", "decision": "READY FOR HUMAN APPROVAL", "reason": "signature check is sound and the tampering case is covered", "head": "${head_sha}", "timestamp": "2026-01-01T00:00:00Z"}
{"hook": "risk-reviewer", "decision": "READY FOR HUMAN APPROVAL", "reason": "constant-time compare, and the signed payload carries no secret", "head": "${head_sha}", "timestamp": "2026-01-01T00:00:00Z"}
EOF
