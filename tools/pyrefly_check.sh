#!/usr/bin/env bash
# Runs pyrefly's typecheck against the source tree Bazel materialized in
# this sandbox (see //:typecheck's `data`) -- pyrefly resolves imports like
# `import _common` across files under [tool.pyrefly].project-includes in
# pyproject.toml, so the whole tree must be laid out together, not per
# package. $1 is the pyrefly binary's runfiles-relative location.
set -euo pipefail
exec "$1" check
