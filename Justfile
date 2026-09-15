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

# Fails if a vendored copy has drifted from src/canon_hooks -- the
# regression guard for sync-hooks, part of `just ci`.
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
    exit $drifted

# Validate the plugin manifest and marketplace. --strict is what CI runs;
# there's no reason to check less strictly locally than CI will.
validate-plugin:
    claude plugin validate --strict ./plugins/claude

# Everything CI runs.
ci: build test lint fmt-check typecheck lock-check sync-check validate-plugin

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
