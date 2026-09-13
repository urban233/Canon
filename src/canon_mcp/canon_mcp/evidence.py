# SPDX-License-Identifier: BSD-3-Clause
"""`canon_evidence` -- whether this commit is green, and where that was
established.

Per docs/plan.md §08's "Why there is no evidence store": a pushed
commit's answer comes from CI, content-addressed by its own SHA; an
unpushed commit has no such record, so the honest answer is a fresh
local re-run, never a cached guess. This module computes both paths
fresh on every call -- nothing here is stored.

`_run_local_check` is `plugins/claude/hooks/stop.py`'s
`_run_verification`, ported (not imported -- see `_git.py`'s module
docstring for why hooks and this package don't share a dependency
edge): same `shlex.split`, same 300s timeout, same 4000-char output
tail on failure.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from ._config import has_verification_signal, load_config
from ._gh import ci_runs_for_commit
from ._git import full_head_sha, is_pushed

_VERIFY_TIMEOUT_SECONDS = 300
_OUTPUT_TAIL_CHARS = 4000


def _run_local_check(root: Path, command: str) -> tuple[bool, str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return False, f"Could not parse the configured verify command: {exc}"
    if not argv:
        return False, "The configured verify command is empty."
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"`{command}` timed out after {_VERIFY_TIMEOUT_SECONDS}s."
    except OSError as exc:
        return False, f"Could not run `{command}`: {exc}"
    if completed.returncode == 0:
        return True, ""
    output = (completed.stdout or "") + (completed.stderr or "")
    return (
        False,
        f"`{command}` exited {completed.returncode}:\n{output[-_OUTPUT_TAIL_CHARS:]}",
    )


def _latest_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The run with the latest `createdAt`, or None for an empty list.

    `gh run list` doesn't document a guaranteed sort order, so this
    picks explicitly rather than trusting list order.
    """
    if not runs:
        return None
    return max(runs, key=lambda run: run.get("createdAt") or "")


def build_evidence(root: Path) -> dict[str, Any]:
    """Whether the current HEAD is green, and where that was
    established: CI for a pushed commit, a fresh local re-run for one
    that isn't."""
    sha = full_head_sha(root)
    if sha is not None and is_pushed(root, sha):
        runs = ci_runs_for_commit(root, sha) or []
        latest = _latest_run(runs)
        green = (
            latest is not None
            and latest.get("status") == "completed"
            and latest.get("conclusion") == "success"
        )
        return {
            "head": sha,
            "pushed": True,
            "source": "ci",
            "runs": runs,
            "green": green if latest is not None else None,
        }

    config = load_config(root)
    if not has_verification_signal(config):
        return {
            "head": sha,
            "pushed": False,
            "source": None,
            "green": None,
            "message": "not pushed, and no verify command configured yet",
        }
    assert config is not None  # has_verification_signal(None) is False, above
    command = config["verify"]
    passed, detail = _run_local_check(root, command)
    return {
        "head": sha,
        "pushed": False,
        "source": "local_rerun",
        "command": command,
        "green": passed,
        "detail": detail,
    }
