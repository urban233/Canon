# SPDX-License-Identifier: BSD-3-Clause
"""Which local branch the current branch is stacked on.

A documented copy of `plan_header.stacked_on`/`base_ref` in
src/canon_hooks/plan_header.py, not an import of it -- see `_git.py`'s
module docstring for why this package and the hooks share no dependency
edge. That function's docstring holds the reasoning; the order is the
same here: the saved plan's `stacked_on:` header, then the branch's own
reflog, then the HEAD reflog, each accepted only when it names an
existing local branch that is a real parent of HEAD -- its fork
point descends from the default branch's.
tests/test_stacked_on_parity.py pins the two copies to the same answer.
"""

from __future__ import annotations

from pathlib import Path

from ._git import _run_git, default_branch, merge_base
from ._plan import branch_plan_relative, read_plan_file

_CREATED_FROM_PREFIX = "branch: Created from "
_MOVING_FROM_PREFIX = "checkout: moving from "


def stacked_on(root: Path, branch: str | None) -> str | None:
    """The local branch `branch` is stacked on, or None."""
    if not branch or branch == "HEAD":
        return None
    default = default_branch(root)
    if branch == default:
        return None
    declared = _declared_stacked_on(root, branch)
    if declared == default:
        return None
    default_fork = merge_base(root, default)
    for candidate in (declared, _reflog_parent(root, branch)):
        if candidate and _is_parent(root, branch, candidate, default, default_fork):
            return candidate
    return None


def base_ref(root: Path, branch: str | None) -> str:
    """The ref `branch`'s base is measured from: its parent step when it
    is stacked, otherwise the default branch."""
    return stacked_on(root, branch) or default_branch(root)


def _declared_stacked_on(root: Path, branch: str) -> str | None:
    plan = read_plan_file(root, branch_plan_relative(branch))
    if plan is None:
        return None
    value = str(plan["header"].get("stacked_on", "")).strip()
    return value or None


def _reflog_parent(root: Path, branch: str) -> str | None:
    created = _run_git(
        root, "reflog", "show", "--format=%gs", f"refs/heads/{branch}", "--"
    )
    if created:
        oldest = created.splitlines()[-1]
        if oldest.startswith(_CREATED_FROM_PREFIX):
            source = oldest[len(_CREATED_FROM_PREFIX) :].strip()
            source = source.removeprefix("refs/heads/")
            if source != "HEAD":
                return source
    moves = _run_git(root, "reflog", "show", "--format=%gs", "HEAD", "--")
    if not moves:
        return None
    suffix = f" to {branch}"
    for entry in reversed(moves.splitlines()):
        if entry.startswith(_MOVING_FROM_PREFIX) and entry.endswith(suffix):
            return entry[len(_MOVING_FROM_PREFIX) : -len(suffix)].strip() or None
    return None


def _is_parent(
    root: Path,
    branch: str,
    candidate: str,
    default: str,
    default_fork: str | None,
) -> bool:
    if candidate in (branch, default):
        return False
    if not _run_git(root, "rev-parse", "--verify", "-q", f"refs/heads/{candidate}"):
        return False
    fork = merge_base(root, candidate)
    if fork is None or fork == default_fork:
        return False
    if default_fork is None:
        return True
    # A real parent's fork point descends from the default fork point;
    # an older one would widen the range rather than narrow it.
    common = _run_git(root, "merge-base", default_fork, fork)
    return common is not None and common.startswith(default_fork)
