# SPDX-License-Identifier: BSD-3-Clause
"""`canon_plan` -- the saved plan for this branch, and its parent if any.

Reads `.canon/plans/<branch>.md` (written by `save_plan.py`'s
`PostToolUse:ExitPlanMode` hook) back, and resolves one level of
`parent:` if the header names one.

`parent:` is written in docs/plan.md §06's own form --
`features/<slug>.md`, relative to `.canon/plans/` rather than to the
repository root. `_resolve_parent` tries that first and falls back to
treating the value as root-relative, because a plan file is a file a
human edits by hand and both spellings are reasonable things to
write. Deeper structure than one level is deliberately not resolved:
`## Steps` lives in the feature plan's body, and computing which step
is current is `canon_position`'s job, not this tool's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._git import current_branch
from ._plan import read_plan_file

_PLANS_DIR_RELATIVE = ".canon/plans"


def _resolve_parent(root: Path, parent_path: str) -> dict[str, Any] | None:
    """The feature plan `parent_path` names, or None if it resolves to
    nothing. Tries §06's `.canon/plans/`-relative form first, then the
    value as written from the repository root."""
    plans_relative = f"{_PLANS_DIR_RELATIVE}/{parent_path.lstrip('/')}"
    return read_plan_file(root, plans_relative) or read_plan_file(root, parent_path)


def build_plan(root: Path) -> dict[str, Any]:
    """The current branch's saved plan, and its parent feature plan if
    the header names one."""
    branch = current_branch(root) or "HEAD"
    plan = read_plan_file(root, f".canon/plans/{branch}.md")
    if plan is None:
        return {
            "branch": branch,
            "plan": None,
            "message": "no plan saved for this branch yet",
        }
    parent_path = plan["header"].get("parent")
    parent = _resolve_parent(root, parent_path) if parent_path else None
    return {"branch": branch, "plan": plan, "parent_plan": parent}
