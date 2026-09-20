# SPDX-License-Identifier: BSD-3-Clause
"""Git plumbing for canon-mcp's tools.

Deliberately duplicated (not imported) from
plugins/claude/hooks/_common.py: hooks run in place from the plugin
directory, standard-library only; this package is its own resolved,
`uvx`-run distribution -- two delivery mechanisms that should not share
a dependency edge, the same "copied and forked" call already made for
CoDev's ported skills (docs/plan.md §14).

`repo_root()` has no hook payload to read a `cwd` from (this is a
long-running server, not a one-shot hook invocation), so it tries four
sources in order:

1. A workspace root the MCP client handed over via the protocol's own
   `roots/list`, recorded by `set_client_root()`. This is the only
   source that works on Antigravity, which substitutes no workspace
   variable into an `mcp_config.json` and spawns the server with its
   working directory set to the *plugin* directory -- so both of the
   next two answer about the wrong tree there. Antigravity's client
   advertises `roots` with `listChanged: true` (confirmed directly).
2. `CLAUDE_PROJECT_DIR` -- set by `.mcp.json` from Claude Code's own
   `${CLAUDE_PROJECT_DIR}` substitution.
3. `git rev-parse --show-toplevel`.
4. The process's own cwd.

Asking the client is preferred over every environment guess because it
is the one source that is *told* rather than inferred. Every function
here returns `None` (or a safe default) rather than raising: a tool that
can't determine something should say so, not crash the server.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

_GIT_TIMEOUT_SECONDS = 10

# Set once at startup from the MCP client's `roots/list`, if it offers
# one. Module state rather than a parameter because `repo_root()` is
# called from every tool and threading it through would change five
# signatures to carry something only one platform supplies.
_client_root: Path | None = None


def adopt_roots(uris: Iterable[str]) -> Path | None:
    """Record the first usable workspace root from a `roots/list` answer.

    Takes the raw `file://` URIs rather than the SDK's `Root` objects, so
    the parsing and the policy live here -- in the typechecked, tested
    part of the package -- rather than in `server.py`, which is excluded
    from typecheck because it imports the MCP SDK.

    "First usable" means: a `file://` URI naming a directory that exists.
    A client may legitimately offer several roots, or offer a file rather
    than a directory, or offer none at all; none of those is an error
    worth failing a tool call over. Returns the adopted root, or None
    when nothing in `uris` qualifies -- in which case the previously
    recorded root is cleared, so a client that stops offering a workspace
    does not leave the server answering about a stale one.
    """
    for uri in uris:
        if not isinstance(uri, str) or not uri.startswith("file://"):
            continue
        # urlparse + url2pathname rather than a manual prefix strip:
        # a root path can contain percent-encoded characters, and a
        # Windows root arrives as file:///C:/... which a naive strip
        # would leave with a leading slash.
        parsed = urlparse(uri)
        candidate = Path(url2pathname(unquote(parsed.path)))
        if candidate.is_dir():
            set_client_root(candidate)
            return candidate
    set_client_root(None)
    return None


def set_client_root(root: Path | None) -> None:
    """Record the workspace root the MCP client reported, if any.

    Called once, after the client answers `roots/list`. A `None` or a
    path that is not a directory clears it rather than being stored: an
    unusable root must fall through to the other sources, never pin the
    server to somewhere that does not exist.
    """
    global _client_root
    _client_root = root if root is not None and root.is_dir() else None


def client_root() -> Path | None:
    """The workspace root the MCP client reported, if it reported one."""
    return _client_root


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
    if _client_root is not None:
        return _client_root
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
