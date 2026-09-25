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
_SHARED_HOOK_FILES := "_common.py _config.py capture_review.py check_scope.py fast_check.py git_guard.py plan_gate.py plan_header.py session_start.py stop.py"

# Every platform whose plugin carries the shared hook core.
_HOOK_PLUGINS := "claude codex antigravity"

# A platform with no plan-mode-exit trigger writes its plan through the
# skill and has the header derived afterwards, by a PostToolUse hook
# scoped to .canon/plans/ -- see normalize_plan.py's own docstring.
# Claude Code has ExitPlanMode and uses save_plan.py instead, which is
# why this is a second, smaller list rather than a line in the one above.
_PLANLESS_HOOK_FILES := "normalize_plan.py"
_PLANLESS_PLUGINS := "codex antigravity"

# canon-relay reuses only `_common.py` -- payload parsing, repo root,
# branch, and `fail_open` -- and none of Canon's gates, which stay in the
# `claude` plugin. A third, one-file list, for the same reason as the one
# above.
_RELAY_HOOK_FILES := "_common.py"
_RELAY_PLUGINS := "canon-relay"

# Vendor src/canon_hooks/*.py into both plugins/*/hooks -- a hook runs via
# bare `python3` with only its own directory on sys.path, so it cannot
# import a sibling package at runtime; this is the mechanical alternative.
sync-hooks:
    #!/usr/bin/env bash
    set -euo pipefail
    for f in {{_SHARED_HOOK_FILES}}; do
        for plugin in {{_HOOK_PLUGINS}}; do
            cp "src/canon_hooks/$f" "plugins/$plugin/hooks/$f"
        done
    done
    for f in {{_PLANLESS_HOOK_FILES}}; do
        for plugin in {{_PLANLESS_PLUGINS}}; do
            cp "src/canon_hooks/$f" "plugins/$plugin/hooks/$f"
        done
    done
    for f in {{_RELAY_HOOK_FILES}}; do
        for plugin in {{_RELAY_PLUGINS}}; do
            cp "src/canon_hooks/$f" "plugins/$plugin/hooks/$f"
        done
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
    for plugin in {{_HOOK_PLUGINS}}; do
        dest="plugins/$plugin/vendor/canon_mcp"
        rm -rf "$dest"
        mkdir -p "$dest"
        cp "{{_CANON_MCP_SRC}}/pyproject.toml" "$dest/pyproject.toml"
        cp -R "{{_CANON_MCP_SRC}}/canon_mcp" "$dest/canon_mcp"
        find "$dest" -name '__pycache__' -type d -exec rm -rf {} +
    done

# decide, review-change, ship and testing-craft are byte-identical between
# plugins/claude/skills and plugins/codex/skills, so they're copied rather
# than hand-maintained twice, the same reasoning as sync-hooks/sync-mcp.
_SHARED_SKILL_DIRS := "decide review-change ship testing-craft"

# frame, plan and review genuinely differ (Codex has no ExitPlanMode tool)
# and stay hand-maintained -- see the plan this branch followed and
# plugins/codex/README.md. Named here, not just in this comment, so
# sync-check's exhaustiveness loop below can tell "known to differ" apart
# from "nobody classified this yet": a skill directory that's in neither
# list used to sync-check silently, the same silent-enumeration drift
# .github/workflows/ci.yml already learned this lesson about once.
_DIVERGENT_SKILL_DIRS := "frame plan review"

# Every plugin that receives the shared skills. plugins/claude is the
# source, so it is not a target.
_SKILL_TARGET_PLUGINS := "codex antigravity"

# Copy the four shared skills from plugins/claude/skills into
# plugins/codex/skills. plugins/claude/skills is the source of truth: it's
# the copy the eval suite actually exercises, so the tested copy is the
# canonical one. Neither copy's text is ever hand-edited to fix drift --
# fix plugins/claude/skills and run this to propagate it.
sync-skills:
    #!/usr/bin/env bash
    set -euo pipefail
    for s in {{_SHARED_SKILL_DIRS}}; do
        for plugin in {{_SKILL_TARGET_PLUGINS}}; do
            rm -rf "plugins/$plugin/skills/$s"
            cp -R "plugins/claude/skills/$s" "plugins/$plugin/skills/$s"
            find "plugins/$plugin/skills/$s" -name '__pycache__' -type d -exec rm -rf {} +
        done
    done

# canon-companion is a skills-only plugin with nothing platform-specific in
# it (no hook, no MCP server, no bundled subagent), so its Codex manifest
# is generated from its Claude one plus "skills": "./skills/" -- the key
# every OpenAI-shipped skills plugin on this machine declares, though a
# real `codex plugin add` confirmed it is not required for skill discovery
# at the default `./skills/` path (see docs/codex-hook-surface.md Part 5;
# plugins/codex ships seven skills with no such key and all seven are
# discoverable). Declared anyway, to match the convention every real
# installed example uses, instead of hand-maintaining a second manifest --
# two hand-edited copies of the same plugin's manifest is exactly the
# duplication this branch exists to stop being casual about.
#
# tools/sync_manifests.py holds the actual generation logic, shared with
# sync-check below, so the two can never disagree about what "in sync"
# means.
sync-manifests:
    #!/usr/bin/env bash
    set -euo pipefail
    python3 tools/sync_manifests.py plugins/canon-companion/.codex-plugin/plugin.json

# Fails if a vendored copy has drifted from src/canon_hooks, src/canon_mcp,
# the four shared skills, or canon-companion's generated Codex manifest --
# the regression guard for sync-hooks/sync-mcp/sync-skills/sync-manifests,
# part of `just ci`. Also fails if a skill directory exists that is in
# neither _SHARED_SKILL_DIRS nor _DIVERGENT_SKILL_DIRS: a skill named in
# no list would sync silently forever, exactly the enumeration drift
# .github/workflows/ci.yml already carries a scar from.
sync-check:
    #!/usr/bin/env bash
    set -euo pipefail
    drifted=0
    for f in {{_SHARED_HOOK_FILES}}; do
        for plugin in {{_HOOK_PLUGINS}}; do
            if ! diff -q "src/canon_hooks/$f" "plugins/$plugin/hooks/$f" > /dev/null; then
                echo "drifted: plugins/$plugin/hooks/$f (run 'just sync-hooks')" >&2
                drifted=1
            fi
        done
    done
    for f in {{_PLANLESS_HOOK_FILES}}; do
        for plugin in {{_PLANLESS_PLUGINS}}; do
            if ! diff -q "src/canon_hooks/$f" "plugins/$plugin/hooks/$f" > /dev/null; then
                echo "drifted: plugins/$plugin/hooks/$f (run 'just sync-hooks')" >&2
                drifted=1
            fi
        done
    done
    for f in {{_RELAY_HOOK_FILES}}; do
        for plugin in {{_RELAY_PLUGINS}}; do
            if ! diff -q "src/canon_hooks/$f" "plugins/$plugin/hooks/$f" > /dev/null; then
                echo "drifted: plugins/$plugin/hooks/$f (run 'just sync-hooks')" >&2
                drifted=1
            fi
        done
    done
    for plugin in {{_HOOK_PLUGINS}}; do
        dest="plugins/$plugin/vendor/canon_mcp"
        if ! diff -q "{{_CANON_MCP_SRC}}/pyproject.toml" "$dest/pyproject.toml" > /dev/null 2>&1 \
            || ! diff -rq -x __pycache__ "{{_CANON_MCP_SRC}}/canon_mcp" "$dest/canon_mcp" > /dev/null 2>&1; then
            echo "drifted: $dest (run 'just sync-mcp')" >&2
            drifted=1
        fi
    done
    for s in {{_SHARED_SKILL_DIRS}}; do
        for plugin in {{_SKILL_TARGET_PLUGINS}}; do
            if ! diff -rq "plugins/claude/skills/$s" "plugins/$plugin/skills/$s" > /dev/null 2>&1; then
                echo "drifted: plugins/$plugin/skills/$s (run 'just sync-skills')" >&2
                drifted=1
            fi
        done
    done
    known="{{_SHARED_SKILL_DIRS}} {{_DIVERGENT_SKILL_DIRS}}"
    for plugin in {{_HOOK_PLUGINS}}; do
        for dir in "plugins/$plugin/skills/"*/; do
            [ -d "$dir" ] || continue
            name="$(basename "$dir")"
            case " $known " in
                *" $name "*) ;;
                *)
                    echo "unclassified: plugins/$plugin/skills/$name is in neither" \
                        "_SHARED_SKILL_DIRS nor _DIVERGENT_SKILL_DIRS in the Justfile" \
                        "-- add it to whichever one actually describes it" >&2
                    drifted=1
                    ;;
            esac
        done
    done
    tmp_manifest="$(mktemp)"
    python3 tools/sync_manifests.py "$tmp_manifest"
    if ! diff -q "$tmp_manifest" "plugins/canon-companion/.codex-plugin/plugin.json" > /dev/null 2>&1; then
        echo "drifted: plugins/canon-companion/.codex-plugin/plugin.json (run 'just sync-manifests')" >&2
        drifted=1
    fi
    rm -f "$tmp_manifest"
    exit $drifted

# Fails if Canon's version is not stated identically in every file that
# states one, or if the newest CHANGELOG.md entry names a different one.
# Distinct from sync-check: that one asks whether a generated copy matches
# its source, this one asks whether the eleven independent declarations
# agree with each other at all. `just ci` was green with mismatched
# versions until this existed -- estimating the 0.1.0 bump produced "six
# version strings" for a tree that had eleven, and nothing caught it.
#
# tools/check_versions.py discovers the files rather than listing them,
# so a manifest added later is covered the day it lands. That is
# deliberate: a hardcoded list is the failure .github/workflows/ci.yml
# and sync-check's skill classification each already carry a scar from.
version-check:
    python3 tools/check_versions.py

# Validate the plugin manifests and marketplace. --strict is what CI runs;
# there's no reason to check less strictly locally than CI will.
#
# Antigravity is checked by our own script rather than by `agy plugin
# validate`, which is the real loader and the better check -- but is an
# IDE-bundled binary with no install path on a CI runner, so wiring it in
# here turned `just ci` red with `sh: 1: agy: not found`. Run `agy plugin
# validate ./plugins/antigravity` locally as well when you have it; the
# script is the portable floor, not a replacement.
validate-plugin:
    claude plugin validate --strict ./plugins/claude
    claude plugin validate --strict ./plugins/canon-companion
    claude plugin validate --strict ./plugins/canon-relay
    python3 tools/check_antigravity_plugin.py plugins/antigravity

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
ci: build test lint fmt-check typecheck lock-check sync-check version-check eval-check validate-plugin

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

# End-to-end check that canon-mcp asks the MCP client for its workspace
# root, and that it does NOT ask a client which never declared the
# capability (which the SDK turns into a hard error -- see ADR 0007).
# Needs uvx to launch the real server, so it is not a Bazel test and not
# part of `ci`; it costs nothing but a process.
check-mcp-roots:
    python3 tools/check_mcp_roots.py src/canon_mcp

# Run the opt-in code-quality skill evals. These are model-backed and remain a
# local, on-demand check for the same cost and credential reasons as `eval`.
eval-companion *args:
    cd plugins/canon-companion && claude plugin eval . \
        --trust-plugin --scaffold --no-publish \
        --allow-tools Bash Write Edit \
        --mocks off \
        {{args}}
