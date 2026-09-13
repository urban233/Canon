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
