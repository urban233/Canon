#!/usr/bin/env bash
# A plain repo -- nothing about this scenario should earn a decision
# record, so decide's own test ("an alternative was seriously
# considered, and the consequence outlives this branch") should
# correctly decline it.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m init
git checkout -q -b feature/rename-helper

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
