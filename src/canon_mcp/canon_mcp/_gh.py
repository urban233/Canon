# SPDX-License-Identifier: BSD-3-Clause
"""GitHub plumbing for `canon_position`, via the `gh` CLI.

Field names confirmed directly against a real PR in this repo (`gh pr
view <n> --json <bad-field>` lists every valid field in its own error
output) rather than assumed: `statusCheckRollup` is a list of check
objects with `status`/`conclusion`; `reviewDecision` is `""` (empty
string, not null) when nothing has reviewed the PR yet.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

_GH_TIMEOUT_SECONDS = 15
_PR_VIEW_FIELDS = "number,url,state,isDraft,reviewDecision,statusCheckRollup"
_RUN_LIST_FIELDS = "databaseId,status,conclusion,workflowName,url,createdAt"
_PR_LIST_FIELDS = "number,url,state,headRefName"
_PR_LIST_LIMIT = "200"


def pr_view(root: Path, branch: str) -> dict[str, Any] | None:
    """The current branch's pull request, or None.

    None covers every non-answer uniformly: `gh` isn't installed, isn't
    authenticated, there's no network, or -- the common case -- there
    simply isn't a pull request for this branch yet. A caller must treat
    all of these the same way: "no PR to report," not an error.
    """
    try:
        completed = subprocess.run(
            ["gh", "pr", "view", branch, "--json", _PR_VIEW_FIELDS],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        parsed = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def pr_list_by_head(root: Path) -> dict[str, dict[str, Any]]:
    """Every pull request in this repository, keyed by head branch name.

    One call rather than one per step: a feature plan with eight steps
    should not cost eight round trips. Same fail-soft contract as
    `pr_view` -- `{}` covers `gh` missing, unauthenticated, offline, or
    a repository with no pull requests, and a caller must treat all of
    them as "no pull request to report".

    The newest pull request wins for a head branch that has had more
    than one, since `gh` lists newest first.
    """
    try:
        completed = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--limit",
                _PR_LIST_LIMIT,
                "--json",
                _PR_LIST_FIELDS,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    try:
        parsed = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(parsed, list):
        return {}
    by_head: dict[str, dict[str, Any]] = {}
    for pull in parsed:
        if not isinstance(pull, dict):
            continue
        head = pull.get("headRefName")
        if isinstance(head, str) and head and head not in by_head:
            by_head[head] = pull
    return by_head


def ci_runs_for_commit(root: Path, sha: str) -> list[dict[str, Any]] | None:
    """Every CI run recorded for the exact commit `sha`, or None.

    Same fail-soft contract as `pr_view`: None covers `gh` missing, not
    authenticated, no network, or no runs at all -- a caller must treat
    all of these as "no evidence to report," not an error.
    """
    try:
        completed = subprocess.run(
            ["gh", "run", "list", "--commit", sha, "--json", _RUN_LIST_FIELDS],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        parsed = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None
