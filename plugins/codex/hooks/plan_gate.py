# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PreToolUse` hook for an edit or a shell command -- the
missing-plan and wrong-branch gate.

Two spine-table rows (docs/plan.md §07) live in one hook, deliberately:
"Editing with no stated intent" and "Editing on main, or a redundant
branch stacked on your own." §12 describes them as the same gate --
"one prompt at the first edit, asking one question: are we somewhere
sensible, and is there a plan for it?"

For an edit: denies when standing on the default branch (branch before
editing), then when no plan is saved for the current branch yet. For a
shell command: denies a `git checkout -b`/`git switch -c` that would nest
a new branch under one the developer already made by hand, and a `git
commit` attempted directly on the default branch.

Mode-aware (docs/plan.md §09): in `pair` and `solo` (the default), a gate
here uses `_common.ask`, an interactive confirmation. In `async`, it never
asks -- a hook has no controlling terminal to detect interactivity either
way (confirmed directly against both supported platforms' hooks
references), so this is read from `.canon/config.json`'s `mode` key, not
sniffed at runtime -- it `_common.deny`s instead, with a reason that tells
the agent to surface the question as its final message rather than
silently proceeding or silently failing. No session-scoped counter is
needed for "ask once": the checks below stop finding anything to gate on
the moment their own condition resolves (a plan gets saved; the branch
changes), which is "once" for free, per Invariant II -- nothing stored to
keep in sync.

Inert without a verification signal (docs/plan.md §07, "No signal, no
Canon"): with no `verify` command in `.canon/config.json` this hook is a
silent no-op. See docs/decisions/0001-what-inert-means.md for why
`stop.py` and `session_start.py` are the two exceptions.

Recognises an edit under any of the tool names a supported platform uses
for one -- `Edit`/`Write` (Claude Code) and `apply_patch` (also offered by
Codex) -- and a shell command under `Bash` (both platforms use this same
name, confirmed directly for Codex rather than assumed from its docs).
"""

from __future__ import annotations

import re
from pathlib import Path

import _common
import _config

_PLANS_DIR_RELATIVE = ".canon/plans"

_EDIT_TOOL_NAMES = ("Edit", "Write", "apply_patch")
_SHELL_TOOL_NAMES = ("Bash",)

_BRANCH_CREATION_PATTERN = re.compile(
    r"\bgit\s+(checkout\s+-b\b|switch\s+-c\b)", re.IGNORECASE
)
_COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)


def _plan_exists(root: Path, branch: str) -> bool:
    return (root / _PLANS_DIR_RELATIVE / f"{branch}.md").is_file()


_ASYNC_SUFFIX = (
    " This session can't wait for an interactive answer, so treat this"
    " as declined for now -- surface the question above as your final"
    " message and let the developer decide."
)


def _gate(root: Path, mode: str, reason: str) -> None:
    if mode == "async":
        full_reason = reason + _ASYNC_SUFFIX
        _common.log_decision(root, "plan_gate.py", "deny", reason=full_reason)
        _common.deny(full_reason)
        return
    _common.log_decision(root, "plan_gate.py", "ask", reason=reason)
    _common.ask(reason)


def _handle_edit(
    root: Path, branch: str, default: str, guard_default: bool, mode: str
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
    if not _plan_exists(root, branch):
        _gate(
            root,
            mode,
            f"No plan is saved for branch '{branch}' yet -- enter plan mode "
            "and get one approved before editing.",
        )
        return
    _common.allow()


def _handle_shell(
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


def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        return
    tool_name = payload.get("tool_name")
    is_edit = tool_name in _EDIT_TOOL_NAMES
    is_shell = tool_name in _SHELL_TOOL_NAMES
    if not is_edit and not is_shell:
        return

    root = _common.repo_root(payload)
    branch = _common.current_branch(root)
    if branch is None:
        return  # can't reliably tell -- don't block on uncertainty
    default = _common.default_branch(root)
    config = _config.load_config(root)
    if not _config.canon_is_active(config):
        return  # no verification signal: Canon is inert, not gating
    guard_default = _config.guard_default_branch(config)
    mode = _config.interaction_mode(config)

    if is_edit:
        _handle_edit(root, branch, default, guard_default, mode)
        return

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return
    _handle_shell(root, command, branch, default, guard_default, mode)


if __name__ == "__main__":
    _common.fail_open(main)()
