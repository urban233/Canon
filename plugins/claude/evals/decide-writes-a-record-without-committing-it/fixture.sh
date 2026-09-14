#!/usr/bin/env bash
# A plain repo with no docs/decisions/ yet -- numbering should start at
# 0001, and the file should never be committed by the agent itself.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit --allow-empty -q -m init
git checkout -q -b feature/storage-format
