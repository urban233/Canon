# SPDX-License-Identifier: BSD-3-Clause
"""`canon_plan` -- the saved plan for this branch, and its parent if any.

Reads `.canon/plans/<branch>.md` (written by `save_plan.py`'s
`PostToolUse:ExitPlanMode` hook) back. Resolves one level of `parent:`
if the header names one -- deeper multi-step feature-plan structure is
the `frame` skill's job (docs/plan.md §14 Phase 2), not built yet, so
this doesn't pretend to resolve more than exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._git import current_branch
from ._plan import read_plan_file


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
    parent = read_plan_file(root, parent_path) if parent_path else None
    return {"branch": branch, "plan": plan, "parent_plan": parent}
