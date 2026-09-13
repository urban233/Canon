# SPDX-License-Identifier: BSD-3-Clause
"""`canon_review` -- which reviewers this diff calls for, and the last
verdict against this HEAD.

`reviewer` is always called for. `risk-reviewer` joins it when the
changed paths (base..HEAD) match a risk surface -- path-based detection
only, scoped to the two categories docs/plan.md §05's architecture tree
names for this exact agent ("auth / data / migration surfaces"), not
the broader four-noun principle in §03: public API surface and generic
"destructive operations" need diff-*content* analysis to mean anything
precise, and a path-only heuristic for either would be too weak to
trust. Substring matching, deliberately biased toward over-flagging: a
false positive here just dispatches an extra reviewer (safe); a false
negative silently skips scrutiny a risky change needed (the direction
that actually matters).

Each verdict comes from `.canon/hooks/decisions.jsonl`, written by the
`SubagentStop` hook (`capture_review.py`) directly from a reviewer
subagent's own final message -- never from the main session's
retelling of it. When more than one reviewer is called for, their
verdicts are combined worst-first into the single `verdict`/`stale`
shape every existing consumer (`position.py`, `ship.py`) already reads,
so neither of them needs to change for this.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._decisions import last_decision
from ._git import changed_paths, default_branch, head_sha, merge_base

_RISK_REVIEWER = "risk-reviewer"
_RISK_SURFACE_KEYWORDS: dict[str, list[str]] = {
    "auth": [
        "auth",
        "permission",
        "acl",
        "rbac",
        "credential",
        "session",
        "login",
        "oauth",
        "sso",
    ],
    "data": ["migration", "alembic", "schema", "backfill", "model"],
}
_SEVERITY_ORDER = [
    "CHANGES REQUIRED",
    "BLOCKED BY MISSING EVIDENCE",
    "READY FOR HUMAN APPROVAL",
]


def _matches_risk_surface(path: str) -> bool:
    lowered = path.lower()
    if lowered.endswith(".sql"):
        return True
    return any(
        keyword in lowered
        for keywords in _RISK_SURFACE_KEYWORDS.values()
        for keyword in keywords
    )


def _reviewers_called_for(root: Path) -> list[str]:
    """`["reviewer"]`, plus `"risk-reviewer"` when a changed path
    matches a risk surface."""
    base = merge_base(root, default_branch(root))
    paths = changed_paths(root, base) if base else None
    reviewers = ["reviewer"]
    if paths and any(_matches_risk_surface(path) for path in paths):
        reviewers.append(_RISK_REVIEWER)
    return reviewers


def _combine(
    verdicts: dict[str, dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, bool]:
    """Combine each reviewer's captured verdict into the single shape
    every existing consumer reads: (combined verdict or None, whether
    any present verdict is stale).

    None when any called-for reviewer has no captured verdict yet --
    with exactly one reviewer this is the only way to get None, so the
    no-risk-surface case behaves exactly as before this module grew a
    second reviewer. With more than one present, the combined verdict
    is the worst by `_SEVERITY_ORDER` (`CHANGES REQUIRED` beats
    `BLOCKED BY MISSING EVIDENCE` beats `READY FOR HUMAN APPROVAL`),
    with per-reviewer reasons concatenated.
    """
    present = [(name, v) for name, v in verdicts.items() if v is not None]
    if len(present) != len(verdicts):
        return None, False
    stale = any(v["stale"] for _, v in present)
    if len(present) == 1:
        _, only = present[0]
        return {k: only[k] for k in ("decision", "reason", "timestamp", "head")}, stale

    def _rank(verdict: dict[str, Any]) -> int:
        decision = verdict.get("decision")
        return _SEVERITY_ORDER.index(decision) if decision in _SEVERITY_ORDER else 0

    _, worst = min(present, key=lambda item: _rank(item[1]))
    reason = "; ".join(
        f"{name}: {v.get('reason')}" for name, v in present if v.get("reason")
    )
    return {
        "decision": worst.get("decision"),
        "reason": reason,
        "timestamp": worst.get("timestamp"),
        "head": worst.get("head"),
    }, stale


def build_review(root: Path) -> dict[str, Any]:
    """The reviewers this diff calls for, and the combined captured
    verdict against the current HEAD, if every called-for reviewer has
    produced one."""
    current_head = head_sha(root)
    reviewers = _reviewers_called_for(root)

    per_reviewer: dict[str, dict[str, Any] | None] = {}
    for name in reviewers:
        record = last_decision(root, name)
        if record is None:
            per_reviewer[name] = None
            continue
        recorded_head = record.get("head")
        per_reviewer[name] = {
            "decision": record.get("decision"),
            "reason": record.get("reason"),
            "timestamp": record.get("timestamp"),
            "head": recorded_head,
            "stale": recorded_head != current_head,
        }

    combined, stale = _combine(per_reviewer)
    if combined is None:
        return {
            "reviewers_called_for": reviewers,
            "verdicts": per_reviewer,
            "verdict": None,
            "current_head": current_head,
            "message": "no reviewer verdict captured yet",
        }
    return {
        "reviewers_called_for": reviewers,
        "verdicts": per_reviewer,
        "verdict": combined,
        "current_head": current_head,
        "stale": stale,
    }
