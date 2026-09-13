#!/usr/bin/env bash
# Runs ruff's lint check against the source tree Bazel materialized in this
# sandbox (see //:lint's `data`). $1 is the ruff binary's runfiles-relative
# location, expanded by the sh_test rule via $(location). Scoped to our own
# source directories, not "." -- the sandbox's working directory also
# contains the ruff/pyrefly binaries' own generated bootstrap scripts
# (pulled in as runfiles of the ":ruff"/":pyrefly" data deps), which "."
# would otherwise pick up as if they were our own code.
set -euo pipefail
exec "$1" check plugins tests tools
