# Canon's build/test/lint/typecheck entry point.
#
# Bazel owns build, test, lint and typecheck -- ruff and pyrefly are real
# Bazel targets (see BUILD.bazel and requirements.in), not commands shelled
# out to. `just` itself is not vendored into this repo; install it via your
# platform's package manager (e.g. a Nix flake, cargo, or
# https://github.com/casey/just).

# Build every target.
build:
    bazel build //...

# Run the test suite.
test *args:
    bazel test //tests/... {{args}}

# Ruff, check-only.
lint:
    bazel test //:lint

# Ruff, format-check-only -- what CI runs.
fmt-check:
    bazel test //:fmt_check

# Ruff, mutates files. Runs against the real checkout, not a sandbox.
fmt:
    bazel run //:fmt

# pyrefly, strict (see pyproject.toml's [tool.pyrefly]).
typecheck:
    bazel test //:typecheck

# Checks requirements_lock.txt hasn't drifted from requirements.in.
lock-check:
    bazel test //:requirements.test

# The hook modules shared, byte-for-byte, between every platform Canon
# ships for -- see src/canon_hooks's own BUILD.bazel and module
# docstrings for what's shared and why. Neither plugin's copy is ever
# hand-edited; fix the one canonical copy under src/canon_hooks and run
# this to propagate it.
_SHARED_HOOK_FILES := "_common.py _config.py capture_review.py check_scope.py git_guard.py plan_gate.py plan_header.py session_start.py stop.py"

# Vendor src/canon_hooks/*.py into both plugins/*/hooks -- a hook runs via
# bare `python3` with only its own directory on sys.path, so it cannot
# import a sibling package at runtime; this is the mechanical alternative.
sync-hooks:
    #!/usr/bin/env bash
    set -euo pipefail
    for f in {{_SHARED_HOOK_FILES}}; do
        cp "src/canon_hooks/$f" "plugins/claude/hooks/$f"
        cp "src/canon_hooks/$f" "plugins/codex/hooks/$f"
    done

# canon-mcp is resolved via `uvx --from <path>`, and that path used to
# reach outside the plugin entirely (`.../plugin-root/../../src/canon_mcp`)
# -- which only exists in this monorepo checkout, never in the copy a real
# marketplace install actually produces (both Claude Code's and Codex's
# plugin managers copy just the plugin's own directory into a separate
# cache location; there is no sibling `src/` tree there). Vendoring
# canon_mcp into each plugin, the same way sync-hooks vendors the shared
# hook core, keeps the server inside the directory that actually survives
# installation.
_CANON_MCP_SRC := "src/canon_mcp"

# Vendor src/canon_mcp into both plugins/*/vendor/canon_mcp. Neither
# plugin's copy is ever hand-edited; fix the one canonical copy under
# src/canon_mcp and run this to propagate it.
sync-mcp:
    #!/usr/bin/env bash
    set -euo pipefail
    for plugin in claude codex; do
        dest="plugins/$plugin/vendor/canon_mcp"
        rm -rf "$dest"
        mkdir -p "$dest"
        cp "{{_CANON_MCP_SRC}}/pyproject.toml" "$dest/pyproject.toml"
        cp -R "{{_CANON_MCP_SRC}}/canon_mcp" "$dest/canon_mcp"
        find "$dest" -name '__pycache__' -type d -exec rm -rf {} +
    done

# Fails if a vendored copy has drifted from src/canon_hooks or
# src/canon_mcp -- the regression guard for sync-hooks/sync-mcp, part of
# `just ci`.
sync-check:
    #!/usr/bin/env bash
    set -euo pipefail
    drifted=0
    for f in {{_SHARED_HOOK_FILES}}; do
        for plugin in claude codex; do
            if ! diff -q "src/canon_hooks/$f" "plugins/$plugin/hooks/$f" > /dev/null; then
                echo "drifted: plugins/$plugin/hooks/$f (run 'just sync-hooks')" >&2
                drifted=1
            fi
        done
    done
    for plugin in claude codex; do
        dest="plugins/$plugin/vendor/canon_mcp"
        if ! diff -q "{{_CANON_MCP_SRC}}/pyproject.toml" "$dest/pyproject.toml" > /dev/null 2>&1 \
            || ! diff -rq -x __pycache__ "{{_CANON_MCP_SRC}}/canon_mcp" "$dest/canon_mcp" > /dev/null 2>&1; then
            echo "drifted: $dest (run 'just sync-mcp')" >&2
            drifted=1
        fi
    done
    exit $drifted

# Validate the plugin manifest and marketplace. --strict is what CI runs;
# there's no reason to check less strictly locally than CI will.
validate-plugin:
    claude plugin validate --strict ./plugins/claude
    claude plugin validate --strict ./plugins/canon-companion

# The companion style checker's tests on whatever `python3` is on PATH,
# outside Bazel on purpose. Bazel pins a hermetic 3.13 (see MODULE.bazel),
# so nothing it runs can see a 3.10-only attribute reference such as
# ast.MatchAs -- which is how that bug survived review here. Point a 3.9
# interpreter at this to check the floor pyproject.toml advertises; CI runs
# it on a real 3.9 in its own job. Deliberately not part of `ci`: under
# Bazel's 3.13 it would pass without testing the thing it exists to test.
test-py39:
    python3 -m unittest discover -s tests -p "*_py39.py" -t . -v

# Static shape check of every eval case's frontmatter -- no model call, no
# credential, no quota. This is deliberately NOT the same thing as `eval`
# below: docs/decisions/0003-eval-suite-is-not-a-ci-gate.md bars wiring the
# billed, model-backed run into CI, and explicitly leaves "everything `just
# ci` already runs" unaffected. A grader that can never pass should fail a
# pull request, not a paid run.
eval-check:
    bazel test //tests:test_evals_graders

# Everything CI runs. `test-py39` is not here on purpose -- see its comment.
ci: build test lint fmt-check typecheck lock-check sync-check eval-check validate-plugin

# Run Canon's own eval suite against its own plugin: a local, on-demand
# check of what the model actually does with the instructions Canon
# ships, never wired into `ci` -- see
# docs/decisions/0003-eval-suite-is-not-a-ci-gate.md.
eval *args:
    cd plugins/claude && claude plugin eval . \
        --trust-plugin --scaffold --no-publish \
        --allow-tools Bash Write Edit "mcp__plugin_canon_canon__*" \
        --mocks off \
        {{args}}

# Run the opt-in code-quality skill evals. These are model-backed and remain a
# local, on-demand check for the same cost and credential reasons as `eval`.
eval-companion *args:
    cd plugins/canon-companion && claude plugin eval . \
        --trust-plugin --scaffold --no-publish \
        --allow-tools Bash Write Edit \
        --mocks off \
        {{args}}
