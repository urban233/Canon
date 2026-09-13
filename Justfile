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

# Validate the plugin manifest and marketplace. --strict is what CI runs;
# there's no reason to check less strictly locally than CI will.
validate-plugin:
    claude plugin validate --strict ./plugins/claude

# Everything CI runs.
ci: build test lint fmt-check typecheck lock-check validate-plugin

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
