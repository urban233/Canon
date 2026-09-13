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
from ._git import (
    changed_paths,
    default_branch,
    file_at_revision,
    head_sha,
    merge_base,
)
from ._notebook import (
    changed_code_cells,
    code_cell_sources,
    is_notebook,
    paired_script,
)

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


_MAX_NOTEBOOKS_REPORTED = 20
_MAX_EXTRACTED_CHARS = 20000


def _notebook_report(root: Path, base: str, path: str) -> dict[str, Any]:
    """What the reviewer needs in order to read one changed notebook.

    docs/plan.md §07: hand over the jupytext `.py` where one exists;
    where neither tool is configured, extract the code cells' source
    "and tell the reviewer what it is looking at, so `execution_count`
    churn is never filed as a finding." The `form` field is that telling
    -- a reviewer that does not know which of the two it has been given
    cannot judge what the absence of output means.

    Nothing is written to the repository: the extracted source is
    returned inline, capped, since it exists to be read once.
    """
    after = file_at_revision(root, "HEAD", path)
    before = file_at_revision(root, base, path)
    report: dict[str, Any] = {
        "path": path,
        "code_cells_changed": changed_code_cells(before, after),
    }
    script = paired_script(root, path)
    if script is not None:
        report["form"] = "jupytext"
        report["script_path"] = script
        report["note"] = (
            f"Review {script}, the jupytext pairing of this notebook, rather "
            "than the .ipynb JSON."
        )
        return report
    sources = code_cell_sources(after) if after is not None else None
    if sources is None:
        report["form"] = "unavailable"
        report["note"] = (
            "This notebook could not be parsed, and the repository configures "
            "neither nbstripout nor jupytext. Say so rather than reviewing the "
            "raw JSON."
        )
        return report
    report["form"] = "extracted"
    report["code_cells"] = len(sources)
    report["source"] = "\n\n# %%\n".join(sources)[:_MAX_EXTRACTED_CHARS]
    report["note"] = (
        "This is the code-cell source Canon extracted from the notebook, not "
        "the file on disk: outputs and execution_count are absent by "
        "construction, so their churn is not a finding."
    )
    return report


def _notebooks(root: Path, base: str | None, paths: list[str] | None) -> list[Any]:
    if not base or not paths:
        return []
    notebooks = [path for path in paths if is_notebook(path)]
    return [
        _notebook_report(root, base, path)
        for path in notebooks[:_MAX_NOTEBOOKS_REPORTED]
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


def _reviewers_called_for(paths: list[str] | None) -> list[str]:
    """`["reviewer"]`, plus `"risk-reviewer"` when a changed path
    matches a risk surface."""
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
    base = merge_base(root, default_branch(root))
    paths = changed_paths(root, base) if base else None
    reviewers = _reviewers_called_for(paths)
    notebooks = _notebooks(root, base, paths)

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
            "notebooks": notebooks,
            "message": "no reviewer verdict captured yet",
        }
    return {
        "reviewers_called_for": reviewers,
        "verdicts": per_reviewer,
        "verdict": combined,
        "current_head": current_head,
        "notebooks": notebooks,
        "stale": stale,
    }
