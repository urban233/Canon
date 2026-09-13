#!/usr/bin/env bash
# Runs ruff's format check (never mutates) against the sandboxed source
# tree. $1 is the ruff binary's runfiles-relative location. Scoped to our
# own source directories -- see ruff_check.sh for why not ".".
set -euo pipefail
exec "$1" format --check plugins tests tools
