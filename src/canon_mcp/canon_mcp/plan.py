# SPDX-License-Identifier: BSD-3-Clause
"""`canon_plan` -- the saved plan for this branch, and its parent if any.

Reads `.canon/plans/<branch>.md` (written by `save_plan.py`'s
`PostToolUse:ExitPlanMode` hook) back, and resolves one level of
`parent:` if the header names one.

`parent:` resolution lives in `_plan.resolve_parent`, shared with
`position.py`. Deeper structure than one level is deliberately not
resolved here: `## Steps` lives in the feature plan's body, and
computing which step is current is `canon_position`'s job, not this
tool's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._git import current_branch
from ._plan import read_plan_file, resolve_parent


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
    parent = resolve_parent(root, parent_path) if parent_path else None
    return {"branch": branch, "plan": plan, "parent_plan": parent}
