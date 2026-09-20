# SPDX-License-Identifier: BSD-3-Clause
"""Read-only slice of Canon's local decisions log.

Deliberately duplicated (not imported) from
plugins/claude/hooks/_common.py's `last_decision` -- see _git.py's
module docstring for why hooks and this package don't share a
dependency edge. `.canon/hooks/decisions.jsonl` is a gitignored,
append-only diagnostic log; this is the one sanctioned read-back of it
(display only, per the hooks' own module docstring), same exception
`last_decision` documents on the hooks side.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DECISIONS_LOG_RELATIVE = ".canon/hooks/decisions.jsonl"


def last_decision(root: Path, hook_name: str) -> dict[str, Any] | None:
    """The most recently logged decision for `hook_name`, or None."""
    path = root / _DECISIONS_LOG_RELATIVE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(record, dict) and record.get("hook") == hook_name:
            return record
    return None
