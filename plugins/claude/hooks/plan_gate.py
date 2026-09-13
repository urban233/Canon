# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PreToolUse:Edit|Write|Bash` hook -- the missing-plan and
wrong-branch gate.

Two spine-table rows (docs/plan.md §07) live in one hook, deliberately:
"Editing with no stated intent" and "Editing on main, or a redundant
branch stacked on your own." §12 describes them as the same gate --
"one prompt at the first edit, asking one question: are we somewhere
sensible, and is there a plan for it?"

For `Edit`/`Write`: denies when standing on the default branch (branch
before editing), then when no plan is saved for the current branch yet.
For `Bash`: denies a `git checkout -b`/`git switch -c` that would nest a
new branch under one the developer already made by hand, and a `git
commit` attempted directly on the default branch.

Every deny here is unconditional (`_common.deny`, never `_common.ask`):
interaction modes (docs/plan.md §09) aren't built yet, and an `ask`
silently degrades to an unexplained `deny` with no interactive
terminal -- so this hook is always explicit rather than sometimes
silent. No session-scoped counter is needed for "ask once": the checks
below stop finding anything to deny the moment their own condition
resolves (a plan gets saved; the branch changes), which is "once" for
free, per Invariant II -- nothing stored to keep in sync.
"""

from __future__ import annotations

import re
from pathlib import Path

import _common
import _config

_PLANS_DIR_RELATIVE = ".canon/plans"

_BRANCH_CREATION_PATTERN = re.compile(
    r"\bgit\s+(checkout\s+-b\b|switch\s+-c\b)", re.IGNORECASE
)
_COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)


def _plan_exists(root: Path, branch: str) -> bool:
    return (root / _PLANS_DIR_RELATIVE / f"{branch}.md").is_file()


def _deny(root: Path, reason: str) -> None:
    _common.log_decision(root, "plan_gate.py", "deny", reason=reason)
    _common.deny(reason)


def _handle_edit_or_write(
    root: Path, branch: str, default: str, guard_default: bool
) -> None:
    if guard_default and branch == default:
        _deny(
            root,
            f"You're on the default branch ({default}) -- branch before "
            "editing. If this repository is genuinely trunk-based, set "
            '"guard_default_branch": false in .canon/config.json.',
        )
        return
    if not _plan_exists(root, branch):
        _deny(
            root,
            f"No plan is saved for branch '{branch}' yet -- enter plan mode "
            "and get one approved before editing.",
        )
        return
    _common.allow()


def _handle_bash(
    root: Path, command: str, branch: str, default: str, guard_default: bool
) -> None:
    if _BRANCH_CREATION_PATTERN.search(command) and branch != default:
        _deny(
            root,
            f"'{branch}' is a branch you made yourself -- adopt it rather "
            "than nesting a new branch under it. If this is genuinely a "
            f"separate change, say explicitly whether to stack on "
            f"'{branch}' or branch from '{default}'.",
        )
        return
    if guard_default and _COMMIT_PATTERN.search(command) and branch == default:
        _deny(
            root,
            f"You're on the default branch ({default}) -- branch before "
            "committing. If this repository is genuinely trunk-based, set "
            '"guard_default_branch": false in .canon/config.json.',
        )
        return
    _common.allow()


def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        return
    tool_name = payload.get("tool_name")
    if tool_name not in ("Edit", "Write", "Bash"):
        return

    root = _common.repo_root(payload)
    branch = _common.current_branch(root)
    if branch is None:
        return  # can't reliably tell -- don't block on uncertainty
    default = _common.default_branch(root)
    guard_default = _config.guard_default_branch(_config.load_config(root))

    if tool_name in ("Edit", "Write"):
        _handle_edit_or_write(root, branch, default, guard_default)
        return

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return
    _handle_bash(root, command, branch, default, guard_default)


if __name__ == "__main__":
    _common.fail_open(main)()
