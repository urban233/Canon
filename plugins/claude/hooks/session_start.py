# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `SessionStart` hook -- position, derived and injected.

"Session starts cold; the agent has no idea where the work stands" is
§07's framing, and this hook is the fix: derive position fresh from git,
the plan file `save_plan.py` writes, `.canon/config.json`, and GitHub,
then inject it as one line of `additionalContext`. Nothing here is
stored -- every fact is recomputed on every invocation, exactly matching
Invariant II ("position is derived, never stored"). This replaces
CoDev's `restore_position` hook *and its state file*.

Scoped exactly to what docs/plan.md §07's `SessionStart` row names:
branch, plan status, diff size, and PR/check state (plus the configured
verify command, a cheap addition). Review state and the rest of
`canon_position`'s eventual scope (§08) are a later, Phase 1 concern.

Every piece degrades independently and silently: a missing plan file, a
failed git command, or a missing/unauthenticated/offline `gh` each drop
only their own piece of the message, never the whole thing. This hook
only ever adds context -- it cannot block a session from starting and
does not try to.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import _common
import _config

_PLAN_STATUS_PATTERN = re.compile(r"^status:\s*(.+?)\s*$", re.MULTILINE)
_GH_TIMEOUT_SECONDS = 15
_PASSING_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_FAILING_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}


def _plan_status(root: Path, branch: str) -> str:
    relative_path = Path(".canon") / "plans" / f"{branch}.md"
    try:
        header = (root / relative_path).read_text(encoding="utf-8")
    except OSError:
        return f"none saved for this branch yet (would be {relative_path})"
    match = _PLAN_STATUS_PATTERN.search(header)
    status = match.group(1) if match else "unknown"
    return f"{status} ({relative_path})"


def _verify_status(root: Path) -> str:
    config = _config.load_config(root)
    if config is not None and _config.has_verification_signal(config):
        return f"`{config['verify']}`"
    return "not configured yet"


def _diff_summary(root: Path, base: str | None) -> str | None:
    if base is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "diff", "--shortstat", f"{base}..HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    stat = completed.stdout.strip()
    return stat or "no changes yet"


def _check_summary(rollup: Any) -> str | None:
    if not isinstance(rollup, list) or not rollup:
        return None
    passing = failing = pending = 0
    for entry in rollup:
        if not isinstance(entry, dict):
            continue
        state = str(entry.get("conclusion") or entry.get("state") or "").upper()
        if state in _PASSING_CONCLUSIONS:
            passing += 1
        elif state in _FAILING_CONCLUSIONS:
            failing += 1
        else:
            pending += 1
    parts = []
    if passing:
        parts.append(f"{passing} passing")
    if failing:
        parts.append(f"{failing} failing")
    if pending:
        parts.append(f"{pending} pending")
    return ", ".join(parts) if parts else None


def _pr_status(root: Path) -> str:
    try:
        completed = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                "--json",
                "number,url,state,statusCheckRollup",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown (gh unavailable)"
    if completed.returncode != 0:
        return "none open for this branch"
    try:
        data = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return "unknown (unexpected gh output)"
    if not isinstance(data, dict):
        return "unknown (unexpected gh output)"
    number = data.get("number")
    state = str(data.get("state", "")).lower() or "unknown"
    checks = _check_summary(data.get("statusCheckRollup"))
    header = f"#{number} ({state})" if number else f"({state})"
    return f"{header}: {checks}" if checks else header


def _position_line(root: Path) -> str:
    branch = _common.current_branch(root) or "unknown"
    default_branch = _common.default_branch(root)
    base = _common.merge_base(root, default_branch)

    parts = [f"Canon position: branch `{branch}`."]
    parts.append(f"Plan: {_plan_status(root, branch)}.")
    parts.append(f"Verify: {_verify_status(root)}.")

    diff = _diff_summary(root, base)
    if diff is not None:
        parts.append(f"Diff vs `{default_branch}`: {diff}.")

    parts.append(f"PR: {_pr_status(root)}.")
    return " ".join(parts)


def main() -> None:
    payload = _common.read_payload()
    root = _common.repo_root(payload)
    _common.context("SessionStart", _position_line(root))


if __name__ == "__main__":
    _common.fail_open(main)()
