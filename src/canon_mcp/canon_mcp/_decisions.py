# SPDX-License-Identifier: BSD-3-Clause
"""Read-only slice of Canon's local decisions log.

Deliberately duplicated (not imported) from
plugins/claude/hooks/_common.py's `last_decision` -- see _git.py's
module docstring for why hooks and this package don't share a
dependency edge. `.canon/hooks/decisions.jsonl` is a gitignored,
append-only local log written by the hooks. This package reads it for
one purpose: `canon_review` takes each reviewer's verdict from it, and
`canon_ship` gates on that verdict -- so a record must answer for the
branch it was captured on and no other.

Every record written since branch scoping carries a `branch` field. A
record without one predates it and matches any branch, so an existing
log keeps answering rather than going silent on upgrade.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DECISIONS_LOG_RELATIVE = ".canon/hooks/decisions.jsonl"


def _records(root: Path) -> list[dict[str, Any]]:
    path = root / _DECISIONS_LOG_RELATIVE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _matches(record: dict[str, Any], hook_name: str, branch: str | None) -> bool:
    if record.get("hook") != hook_name:
        return False
    recorded = record.get("branch")
    return branch is None or recorded is None or recorded == branch


def decisions_for(
    root: Path, hook_name: str, branch: str | None = None
) -> list[dict[str, Any]]:
    """Every logged decision for `hook_name` on `branch`, oldest first."""
    return [r for r in _records(root) if _matches(r, hook_name, branch)]


def last_decision(
    root: Path, hook_name: str, branch: str | None = None
) -> dict[str, Any] | None:
    """The most recently logged decision for `hook_name` on `branch`, or
    None."""
    matching = decisions_for(root, hook_name, branch)
    return matching[-1] if matching else None
