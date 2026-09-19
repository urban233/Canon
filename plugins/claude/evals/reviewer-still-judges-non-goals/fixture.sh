#!/usr/bin/env bash
# The change adds a retry to a network call and deliberately does not
# add a backoff. The plan's `## Non-goals` records that omission as a
# decision, with a reason. A general-purpose code review has no access
# to that plan and is very likely to file "retries with no backoff" as a
# finding -- correctly, on the code alone.
#
# This case exists because delegating the finding-hunting must not
# delegate Canon's own judgement with it. reviewer.md's rule is to judge
# every finding against the saved plan's Non-goals before carrying it: a
# deliberate omission recorded there is the author having decided, not a
# gap. Delete that rule and the reviewer forwards the host review's
# finding as its own and demands a change the developer already declined.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src
cat > src/fetcher.py <<'EOF'
import urllib.request


def fetch(url):
    """Fetch `url` once."""
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read()
EOF
git add src/fetcher.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "fetcher: single attempt"
git checkout -q -b retry-transient-failures

cat > src/fetcher.py <<'EOF'
import urllib.request

ATTEMPTS = 3


def fetch(url):
    """Fetch `url`, retrying a transient failure."""
    last_error = None
    for _ in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.read()
        except OSError as error:
            last_error = error
    raise last_error
EOF
git add src/fetcher.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "fetcher: retry a transient failure"

mkdir -p .canon/plans
cat > .canon/plans/retry-transient-failures.md <<'EOF'
---
status: approved
base:
scope: [src/**]
done: "a transient failure is retried instead of surfacing immediately"
verify:
parent:
---

## Approach
Wrap the existing `urlopen` call in a bounded retry loop, re-raising the
last error when every attempt has failed.

## Non-goals
**No backoff between attempts.** This was considered and rejected for
this change: the only caller is an interactive command with a five
second timeout per attempt, and a sleeping retry would blow past the
latency budget the command is held to. Adding a backoff is its own
change, against its own plan, once a non-interactive caller exists.

## Verification
`true`
EOF

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
