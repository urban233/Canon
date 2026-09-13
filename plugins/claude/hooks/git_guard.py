# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PreToolUse:Bash` hook -- the destructive-git guard and
commit-trailer stripper.

Two independent jobs, per docs/plan.md §07's "Destructive git run
casually" spine-table row and §12's authorship section:

1. A short, fixed list of destructive git operations -- exactly the
   five §07 names (force push, hard reset, forced clean, branch
   deletion, merge) -- are denied outright, always, with no exception
   and no `ask`: these are the operations §12's table marks "never" for
   Canon regardless of interaction mode. `rebase` onto a shared branch
   and `tag` deletion are in §12's broader table too, but both need a
   "is this actually shared" judgement this hook doesn't make, so
   they're left out rather than guessed at.
2. `git commit` commands carrying a `Co-Authored-By:` trailer have it
   stripped via `updatedInput` before the commit runs -- the mechanised
   half of §12's authorship guidance ("the git guard, which is already
   inspecting `git commit`, strips any AI-attribution trailer it
   finds"). Scoped to `git commit` only: a `gh pr create --body` is a
   separate surface, and §12 explicitly leaves that to documentation
   rather than mechanising it here.

Like `plan_gate.py`, this hook only ever denies, never asks -- see that
module's docstring for why.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import _common

_NON_DELIMITER = r"[^|;&]*"
_DESTRUCTIVE_PATTERNS = [
    (
        re.compile(rf"\bgit\s+push\b{_NON_DELIMITER}(--force\b|-f\b)"),
        "a force push",
    ),
    (
        re.compile(rf"\bgit\s+reset\b{_NON_DELIMITER}--hard\b"),
        "a hard reset",
    ),
    (
        re.compile(
            rf"\bgit\s+clean\b{_NON_DELIMITER}-\w*f\w*d\w*"
            rf"|\bgit\s+clean\b{_NON_DELIMITER}-\w*d\w*f\w*"
        ),
        "a forced clean of untracked files/directories",
    ),
    (
        re.compile(rf"\bgit\s+branch\b{_NON_DELIMITER}(-D\b|--delete\b)"),
        "a branch deletion",
    ),
    (
        re.compile(rf"\bgit\s+push\b{_NON_DELIMITER}(--delete\b|:\S)"),
        "a remote branch deletion",
    ),
    (re.compile(r"\bgit\s+merge\b"), "a merge"),
]

_COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)
_TRAILER_LINE = re.compile(r"^[ \t]*Co-Authored-By:.*\n?", re.IGNORECASE | re.MULTILINE)


def _matched_destructive_operation(command: str) -> str | None:
    for pattern, label in _DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            return label
    return None


def _strip_attribution(command: str) -> str | None:
    """The command with every `Co-Authored-By:` trailer line removed, or
    None if there was nothing to strip."""
    stripped = _TRAILER_LINE.sub("", command)
    return stripped if stripped != command else None


def _allow_with_updated_command(tool_input: dict[str, Any], command: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {**tool_input, "command": command},
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        return
    if payload.get("tool_name") != "Bash":
        return
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return

    root = _common.repo_root(payload)

    label = _matched_destructive_operation(command)
    if label is not None:
        reason = (
            f"Canon never runs {label} -- if you genuinely want this, run it yourself."
        )
        _common.log_decision(root, "git_guard.py", "deny", reason=reason)
        _common.deny(reason)
        return

    if _COMMIT_PATTERN.search(command):
        stripped = _strip_attribution(command)
        if stripped is not None:
            _common.log_decision(
                root,
                "git_guard.py",
                "stripped_attribution",
                reason="removed a Co-Authored-By trailer from a git commit",
            )
            assert isinstance(tool_input, dict)
            _allow_with_updated_command(tool_input, stripped)
            return


if __name__ == "__main__":
    _common.fail_open(main)()
