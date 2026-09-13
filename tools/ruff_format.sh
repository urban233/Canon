#!/usr/bin/env bash
# Mutates the real working tree -- run via `bazel run //:fmt`, never `bazel
# test`, since only `bazel run` sets $BUILD_WORKSPACE_DIRECTORY (the actual
# repo checkout, not this target's read-only sandbox). $1 is the ruff
# binary's runfiles-relative location.
set -euo pipefail
if [[ -z "${BUILD_WORKSPACE_DIRECTORY:-}" ]]; then
    echo "run this via 'bazel run //:fmt', not 'bazel test'" >&2
    exit 1
fi
ruff="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
cd "$BUILD_WORKSPACE_DIRECTORY"
exec "$ruff" format .
