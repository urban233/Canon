# SPDX-License-Identifier: BSD-3-Clause
"""`canon_review` -- which reviewers this diff calls for, and the last
verdict against this HEAD.

"Which reviewers" is honestly always `["reviewer"]` for now:
risk-surface detection and the `risk-reviewer` agent are Phase 2 per
docs/plan.md §14, not faked here. The verdict itself comes from
`.canon/hooks/decisions.jsonl`, written by the `SubagentStop` hook
(`capture_review.py`) directly from the reviewer subagent's own final
message -- never from the main session's retelling of it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._decisions import last_decision
from ._git import head_sha

_REVIEWERS_CALLED_FOR = ["reviewer"]


def build_review(root: Path) -> dict[str, Any]:
    """The reviewers this diff calls for, and the last captured verdict
    against the current HEAD, if any."""
    current_head = head_sha(root)
    record = last_decision(root, "reviewer")
    if record is None:
        return {
            "reviewers_called_for": _REVIEWERS_CALLED_FOR,
            "verdict": None,
            "current_head": current_head,
            "message": "no reviewer verdict captured yet",
        }
    recorded_head = record.get("head")
    return {
        "reviewers_called_for": _REVIEWERS_CALLED_FOR,
        "verdict": {
            "decision": record.get("decision"),
            "reason": record.get("reason"),
            "timestamp": record.get("timestamp"),
            "head": recorded_head,
        },
        "current_head": current_head,
        "stale": recorded_head != current_head,
    }
