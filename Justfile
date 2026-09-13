# Canon's build/test/lint/typecheck entry point.
#
# Bazel owns build and test; `uvx` owns developer tooling (ruff, pyrefly) so
# no pip dependency hub exists yet -- see docs/plan.md's Non-goals for why.
# `just` itself is not vendored into this repo; install it via your platform's
# package manager (e.g. a Nix flake, cargo, or https://github.com/casey/just).

RUFF_VERSION := "0.16.7"
PYREFLY_VERSION := "1.3.0"

# Build every target.
build:
    bazel build //...

# Run the test suite.
test *args:
    bazel test //tests/... {{args}}

# Ruff, check-only.
lint:
    uvx ruff@{{RUFF_VERSION}} check .

# Ruff, format-check-only -- what CI runs.
fmt-check:
    uvx ruff@{{RUFF_VERSION}} format --check .

# Ruff, mutates files.
fmt:
    uvx ruff@{{RUFF_VERSION}} format .

# pyrefly, strict (see pyproject.toml's [tool.pyrefly]).
typecheck:
    uvx pyrefly@{{PYREFLY_VERSION}} check

# Validate the plugin manifest and marketplace.
validate-plugin:
    claude plugin validate ./plugins/claude

# Everything CI runs.
ci: build test lint fmt-check typecheck validate-plugin
