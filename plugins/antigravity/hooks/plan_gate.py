# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PreToolUse:replace_file_content|write_to_file|run_command` hook --
the missing-plan and wrong-branch gate (Antigravity port).

Two spine-table rows (docs/plan.md §07) live in one hook, deliberately:
"Editing with no stated intent" and "Editing on main, or a redundant
branch stacked on your own." §12 describes them as the same gate --
"one prompt at the first edit, asking one question: are we somewhere
sensible, and is there a plan for it?"

For `replace_file_content`/`write_to_file`:
- Denies/asks when standing on the default branch (branch before editing).
- Exemption: writing to `.canon/plans/` is allowed on non-default branches
  so the agent can author the initial plan without being blocked.
- Denies/asks when no plan is saved for the current branch yet.

For `run_command`:
- Denies/asks a `git checkout -b`/`git switch -c` that would nest a
  new branch under one the developer already made by hand.
- Denies/asks a `git commit` attempted directly on the default branch.

Mode-aware (docs/plan.md §09):
- In `pair` and `solo` (the default), gates using `_common.ask`
  (interactive confirmation).
- In `async`, gates using `_common.deny` with a reason instructing the agent to surface
  the question to the developer.

Inert without a verification signal: with no `verify` command in `.canon/config.json`
this hook is a silent allow.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_hooks_dir = str(Path(__file__).resolve().parent)
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

import _common_agy as _common  # noqa: E402
import _config  # noqa: E402
import plan_header  # noqa: E402

_PLANS_DIR_RELATIVE = ".canon/plans"

_BRANCH_CREATION_PATTERN = re.compile(
    r"\bgit\s+(checkout\s+(-b\b|--orphan\b)|switch\s+(-c\b|--create\b|--force-create\b|--orphan\b))",
    re.IGNORECASE,
)
_COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)

_RECOGNIZED_EDIT_TOOLS = {
    "replace_file_content",
    "write_to_file",
    "Edit",
    "Write",
}

_RECOGNIZED_COMMAND_TOOLS = {
    "run_command",
    "Bash",
}

_ASYNC_SUFFIX = (
    " This session can't wait for an interactive answer, so treat this"
    " as declined for now -- surface the question above as your final"
    " message and let the developer decide."
)


def _plan_exists(root: Path, branch: str) -> bool:
    return plan_header.branch_plan_path(root, branch).is_file()


def _is_plans_path(root: Path, target_file: str) -> bool:
    """Check whether target_file is located within `.canon/plans/`."""
    try:
        p = Path(target_file)
        if not p.is_absolute():
            p = root / p
        plans_dir = (root / _PLANS_DIR_RELATIVE).resolve()
        p.resolve().relative_to(plans_dir)
        return True
    except (ValueError, OSError):
        return False


def _gate(root: Path, mode: str, reason: str) -> None:
    if mode == "async":
        full_reason = reason + _ASYNC_SUFFIX
        _common.log_decision(root, "plan_gate.py", "deny", reason=full_reason)
        _common.deny(full_reason)
        return
    _common.log_decision(root, "plan_gate.py", "ask", reason=reason)
    _common.ask(reason)


def _handle_edit_or_write(
    root: Path,
    target_file: str | None,
    branch: str,
    default: str,
    guard_default: bool,
    mode: str,
) -> None:
    if guard_default and branch == default:
        _gate(
            root,
            mode,
            f"You're on the default branch ({default}) -- branch before "
            "editing. If this repository is genuinely trunk-based, set "
            '"guard_default_branch": false in .canon/config.json.',
        )
        return

    # Bootstrapping exemption: writing a plan file into .canon/plans/ is allowed
    if target_file and _is_plans_path(root, target_file):
        _common.allow()
        return

    if not _plan_exists(root, branch):
        _gate(
            root,
            mode,
            f"No plan is saved for branch '{branch}' yet -- enter plan mode "
            "and get one approved before editing.",
        )
        return

    _common.allow()


def _handle_command(
    root: Path, command: str, branch: str, default: str, guard_default: bool, mode: str
) -> None:
    if _BRANCH_CREATION_PATTERN.search(command) and branch != default:
        _gate(
            root,
            mode,
            f"'{branch}' is a branch you made yourself -- adopt it rather "
            "than nesting a new branch under it. If this is genuinely a "
            f"separate change, say explicitly whether to stack on "
            f"'{branch}' or branch from '{default}'.",
        )
        return
    if guard_default and _COMMIT_PATTERN.search(command) and branch == default:
        _gate(
            root,
            mode,
            f"You're on the default branch ({default}) -- branch before "
            "committing. If this repository is genuinely trunk-based, set "
            '"guard_default_branch": false in .canon/config.json.',
        )
        return
    _common.allow()


@_common.fail_open(fallback_fn=_common.allow)
def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        _common.allow()
        return

    tool_name = _common.tool_name(payload)
    if not tool_name or (
        tool_name not in _RECOGNIZED_EDIT_TOOLS
        and tool_name not in _RECOGNIZED_COMMAND_TOOLS
    ):
        _common.allow()
        return

    if not _common.has_workspace(payload):
        _common.allow()
        return

    root = _common.repo_root(payload)
    if not root.is_dir():
        _common.allow()
        return

    branch = _common.current_branch(root)
    if branch is None:
        _common.allow()
        return  # can't reliably tell -- don't block on uncertainty

    default = _common.default_branch(root)
    config = _config.load_config(root)
    if not _config.canon_is_active(config):
        _common.allow()
        return  # no verification signal: Canon is inert, not gating

    guard_default = _config.guard_default_branch(config)
    mode = _config.interaction_mode(config)

    if tool_name in _RECOGNIZED_EDIT_TOOLS:
        target_file = _common.tool_target_file(payload)
        _handle_edit_or_write(root, target_file, branch, default, guard_default, mode)
        return

    command = _common.tool_command(payload)
    if not command:
        _common.allow()
        return
    _handle_command(root, command, branch, default, guard_default, mode)


if __name__ == "__main__":
    main()
