# SPDX-License-Identifier: BSD-3-Clause
"""Git plumbing for canon-mcp's tools.

Deliberately duplicated (not imported) from
plugins/claude/hooks/_common.py: hooks run in place from the plugin
directory, standard-library only; this package is its own resolved,
`uvx`-run distribution -- two delivery mechanisms that should not share
a dependency edge, the same "copied and forked" call already made for
CoDev's ported skills (docs/plan.md §14).

`repo_root()` has no hook payload to read a `cwd` from (this is a
long-running server, not a one-shot hook invocation), so it prefers the
`CLAUDE_PROJECT_DIR` environment variable -- set by `.mcp.json` from
Claude Code's own `${CLAUDE_PROJECT_DIR}` substitution -- then falls
back to `git rev-parse --show-toplevel`, then the process's own cwd.
Every function here returns `None` (or a safe default) rather than
raising: a tool that can't determine something should say so, not
crash the server.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 10


def _run_git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def repo_root() -> Path:
    """The repository root this server should act on.

    Never raises: a server that can't determine the root still needs to
    answer *something* rather than crash.
    """
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        return Path(env_dir)
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode == 0:
            candidate = completed.stdout.strip()
            if candidate:
                return Path(candidate)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path.cwd()


def current_branch(root: Path) -> str | None:
    """The current branch name, or None if it can't be determined."""
    return _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")


def default_branch(root: Path) -> str:
    """The repository's default branch, best-effort.

    Reads `origin/HEAD`; falls back to "main" when there's no such
    remote ref rather than failing outright.
    """
    ref = _run_git(root, "rev-parse", "--abbrev-ref", "origin/HEAD")
    if ref and ref.startswith("origin/"):
        return ref[len("origin/") :]
    return "main"


def merge_base(root: Path, default_branch_name: str) -> str | None:
    """The short SHA where the current branch diverged from
    `default_branch_name`, or None if that can't be determined."""
    sha = _run_git(root, "merge-base", "HEAD", default_branch_name)
    return sha[:9] if sha else None


def head_sha(root: Path) -> str | None:
    """The current HEAD's short SHA, or None if that can't be determined."""
    sha = _run_git(root, "rev-parse", "HEAD")
    return sha[:9] if sha else None


def full_head_sha(root: Path) -> str | None:
    """The current HEAD's full SHA, or None if that can't be determined.

    Unlike `head_sha`, this is not truncated -- `gh run list --commit`
    needs the exact SHA to avoid ambiguity, where the other callers of
    `head_sha` only need something short enough to display.
    """
    return _run_git(root, "rev-parse", "HEAD")


def is_pushed(root: Path, sha: str) -> bool:
    """Whether `sha` exists in the history of any remote-tracking
    branch.

    `git branch -r --contains` rather than comparing against the
    current branch's own `@{u}` -- this stays correct even if the local
    branch's own upstream tracking is stale or unset, so long as the
    commit reached *some* remote branch.
    """
    return bool(_run_git(root, "branch", "-r", "--contains", sha))


def changed_paths(root: Path, base_sha: str) -> list[str] | None:
    """The files that differ between `base_sha` and HEAD, or None if
    that couldn't be determined.

    This also covers a genuinely empty diff, indistinguishable from
    `_run_git`'s own None-on-empty-output return -- every caller treats
    both the same way: nothing to flag.
    """
    output = _run_git(root, "diff", "--name-only", f"{base_sha}..HEAD")
    return output.splitlines() if output else None


def branch_names(root: Path) -> set[str]:
    """Every local and remote branch name, remotes stripped of `origin/`.

    Empty set rather than None on any failure -- a caller asking "does a
    branch for this step exist?" treats not-found and cannot-tell the
    same way, and there is nothing useful to distinguish.
    """
    names: set[str] = set()
    for args, strip in (
        (("branch", "--format=%(refname:short)"), False),
        (("branch", "-r", "--format=%(refname:short)"), True),
    ):
        output = _run_git(root, *args)
        if not output:
            continue
        for line in output.splitlines():
            name = line.strip()
            if not name or "->" in name:
                continue
            if strip:
                name = name.split("/", 1)[1] if "/" in name else name
            names.add(name)
    return names


def merged_branch_names(root: Path, default_branch_name: str) -> set[str]:
    """Branches already merged into `default_branch_name`, remotes
    stripped. Evidence of a landed step for a repository that does not
    delete its branches on merge."""
    output = _run_git(
        root,
        "branch",
        "-a",
        "--merged",
        default_branch_name,
        "--format=%(refname:short)",
    )
    if not output:
        return set()
    names: set[str] = set()
    for line in output.splitlines():
        name = line.strip()
        if not name or "->" in name:
            continue
        if name.startswith("origin/"):
            name = name[len("origin/") :]
        names.add(name)
    return names


def file_at_revision(root: Path, revision: str, path: str) -> str | None:
    """The contents of `path` as of `revision`, or None.

    None covers a path that did not exist then, which is how a newly
    added file reads -- callers treat that as "no previous version",
    not as an error.
    """
    return _run_git(root, "show", f"{revision}:{path}")


def commits_ahead(root: Path, base_sha: str | None) -> int | None:
    """How many commits HEAD is ahead of `base_sha`, or None if either
    that count or `base_sha` itself couldn't be determined."""
    if not base_sha:
        return None
    count = _run_git(root, "rev-list", "--count", f"{base_sha}..HEAD")
    if count is None or not count.isdigit():
        return None
    return int(count)
