# SPDX-License-Identifier: BSD-3-Clause
"""`canon_ship` -- whether this is ready for a human, and precisely what's
missing if not.

Deliberately narrower than `canon_position`: `position.py` navigates the
whole lifecycle (no plan yet, no verify configured, no PR yet, CI still
running, ...), while this answers one question -- are the three
invariants (plan satisfied, evidence green at this HEAD, independent
verdict present) met right now -- with a structured per-invariant
breakdown the `ship` skill can act on, rather than a single sentence.
Composes entirely out of state the other tools already derive; nothing
new is stored, read, or computed from scratch here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._git import current_branch
from ._plan import read_plan_file
from .evidence import build_evidence
from .review import build_review


def _plan_readiness(plan: dict[str, Any] | None) -> tuple[bool, str | None]:
    if plan is None:
        return False, "no plan saved for this branch yet"
    header = plan["header"]
    status = header.get("status", "")
    if status and status != "approved":
        return False, f"plan status is '{status}', not approved"
    notes = header.get("notes")
    if notes:
        return False, f"plan is missing required sections: {notes}"
    return True, None


def _evidence_reason(evidence: dict[str, Any]) -> str:
    green = evidence.get("green")
    if green is None:
        message = evidence.get("message") or "evidence is not yet known"
        return f"HEAD is not verified green yet: {message}"
    detail = evidence.get("detail") or "the configured verification failed"
    return f"HEAD is not green: {detail}"


def _review_readiness(review: dict[str, Any]) -> tuple[bool, str | None]:
    verdict = review.get("verdict")
    if verdict is None:
        return False, "no reviewer verdict captured yet -- dispatch the reviewer"
    if review.get("stale"):
        return False, "the reviewer verdict is stale -- HEAD has moved since it ran"
    decision = verdict.get("decision")
    if decision == "READY FOR HUMAN APPROVAL":
        return True, None
    if decision == "CHANGES REQUIRED":
        return False, f"the reviewer requested changes: {verdict.get('reason')}"
    if decision == "BLOCKED BY MISSING EVIDENCE":
        return False, f"the reviewer is blocked: {verdict.get('reason')}"
    return False, f"unrecognized reviewer verdict: {decision}"


def build_ship(root: Path) -> dict[str, Any]:
    """Whether the three invariants are met right now, and what's
    missing if not."""
    branch = current_branch(root) or "HEAD"
    plan = read_plan_file(root, f".canon/plans/{branch}.md")
    plan_ok, plan_reason = _plan_readiness(plan)

    evidence = build_evidence(root)
    evidence_ok = evidence.get("green") is True
    evidence_reason = None if evidence_ok else _evidence_reason(evidence)

    review = build_review(root)
    review_ok, review_reason = _review_readiness(review)

    missing = [r for r in (plan_reason, evidence_reason, review_reason) if r]
    ready = plan_ok and evidence_ok and review_ok
    return {
        "ready": ready,
        "plan": {"satisfied": plan_ok, "reason": plan_reason},
        "evidence": evidence,
        "review": review,
        "missing": missing,
        "message": (
            "Ready for a human: plan satisfied, HEAD is green, and the "
            "reviewer says READY FOR HUMAN APPROVAL."
            if ready
            else "Not ready yet: " + "; ".join(missing)
        ),
    }
