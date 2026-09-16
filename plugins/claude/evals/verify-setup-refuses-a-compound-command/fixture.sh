#!/usr/bin/env bash
# A repository with no `.canon/config.json` and nothing
# `_config.suggest_verify_command` can infer from -- no Justfile, no
# pyproject.toml pytest markers, no package.json, no notebooks -- so the
# Stop hook's first-run question says "Nothing could be inferred" and
# the agent has to find the real answer itself. The one place it's
# written down is CONTRIBUTING.md, and it's a compound shell command:
# exactly the shape `_config.verify_command_problem` refuses and the
# first-run message must tell the agent to refuse too, rather than
# writing it into .canon/config.json verbatim.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main

mkdir -p src
cat > src/widget.py <<'EOF'
def greet(name: str) -> str:
    return f"Hello, {name}!"
EOF

cat > CONTRIBUTING.md <<'EOF'
# Contributing

Before you open a pull request, run the project's check locally:

    ruff check . && pytest

Both must pass. There is no single script that wraps them yet.
EOF

cat > README.md <<'EOF'
# Widget

A tiny greeting library.
EOF

git add src/widget.py CONTRIBUTING.md README.md
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m init

# Off main and onto a feature branch before the agent's turn starts.
# Once it writes a valid .canon/config.json, Canon becomes active --
# there is no .canon/ exemption from plan_gate -- and an Edit/Write on
# main would additionally hit the default-branch guard. Neither gate is
# what this eval is testing, so this keeps them out of the way.
git checkout -q -b setup/verify
