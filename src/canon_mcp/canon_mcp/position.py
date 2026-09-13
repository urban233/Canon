# SPDX-License-Identifier: BSD-3-Clause
"""`canon_position` -- where the work stands, computed fresh every call.

Every field is derived from git, `.canon/config.json`, the saved plan
file, `gh pr view`, and (as of Phase 1) `canon_review`'s own captured
reviewer verdict at call time -- nothing is stored, per docs/plan.md's
Invariant II. `next_step`'s review branch is driven by Canon's own
captured verdict, not GitHub's native `reviewDecision` field (still
visible on `pull_request` for anyone who wants it) -- that's the point
of Invariant III: the verdict Canon acts on is the one the reviewer
subagent produced, not a retelling of it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._config import has_verification_signal, load_config
from ._gh import pr_view
from ._git import commits_ahead, current_branch, default_branch, head_sha, merge_base
from ._plan import read_plan_file
from .review import build_review

_INCOMPLETE_CHECK_STATUS = "COMPLETED"
_FAILING_CHECK_CONCLUSIONS = {
    "FAILURE",
    "ERROR",
    "CANCELLED",
    "TIMED_OUT",
    "ACTION_REQUIRED",
}


def _plan_summary(plan: dict[str, Any] | None) -> dict[str, str] | None:
    if plan is None:
        return None
    header = plan["header"]
    return {
        "status": header.get("status", ""),
        "done": header.get("done", ""),
        "verify": header.get("verify", ""),
    }


def _check_state(pr: dict[str, Any]) -> tuple[str | None, str | None]:
    """(name of a failing check, name of an incomplete check) found in
    `pr`'s `statusCheckRollup`, whichever is found first; either may be
    None if nothing of that kind is present."""
    for check in pr.get("statusCheckRollup") or []:
        name = check.get("name") or "a check"
        if check.get("conclusion") in _FAILING_CHECK_CONCLUSIONS:
            return name, None
        if check.get("status") != _INCOMPLETE_CHECK_STATUS:
            return None, name
    return None, None


def _next_step(
    verify_ok: bool,
    plan: dict[str, Any] | None,
    pr: dict[str, Any] | None,
    review: dict[str, Any],
) -> str:
    if not verify_ok:
        return (
            ".canon/config.json has no verify command yet -- run first-run "
            "setup: tell Canon what command should pass before a turn ends"
        )
    if plan is None:
        return "enter plan mode and get a plan approved before making changes"
    if pr is None:
        return "push this branch and open a pull request when the work is ready"
    number = pr.get("number")
    if pr.get("state") != "OPEN":
        state = str(pr.get("state", "unknown")).lower()
        return f"PR #{number} is {state} -- nothing further to do on this branch"
    failing, incomplete = _check_state(pr)
    if failing:
        return f"fix the failing check ({failing}) on PR #{number}"
    if incomplete:
        return f"wait for CI to finish ({incomplete}) on PR #{number}"
    verdict = review.get("verdict")
    if verdict is None:
        return f"dispatch the reviewer subagent for PR #{number}"
    if review.get("stale"):
        return (
            f"dispatch the reviewer again for PR #{number} -- HEAD has moved "
            "since the last verdict"
        )
    decision = verdict.get("decision")
    if decision == "CHANGES REQUIRED":
        return f"address the reviewer's requested changes on PR #{number}"
    if decision == "BLOCKED BY MISSING EVIDENCE":
        return (
            f"resolve what's blocking review on PR #{number}: {verdict.get('reason')}"
        )
    if decision == "READY FOR HUMAN APPROVAL":
        return f"PR #{number} is reviewed and green -- ready for a human to merge"
    return f"PR #{number}'s reviewer verdict is unrecognized: {decision}"


def build_position(root: Path) -> dict[str, Any]:
    """Where the work stands and the single next step."""
    branch = current_branch(root) or "HEAD"
    default = default_branch(root)
    base = merge_base(root, default)
    head = head_sha(root)
    ahead = commits_ahead(root, base)
    plan = read_plan_file(root, f".canon/plans/{branch}.md")
    verify_ok = has_verification_signal(load_config(root))
    # No PR to ask about while standing on the default branch itself.
    pr = pr_view(root, branch) if branch != default else None
    review = build_review(root)
    next_step = _next_step(verify_ok, plan, pr, review)
    ahead_text = str(ahead) if ahead is not None else "an unknown number of"
    return {
        "branch": branch,
        "default_branch": default,
        "base": base,
        "head": head,
        "commits_ahead": ahead,
        "verify_configured": verify_ok,
        "plan": _plan_summary(plan),
        "pull_request": pr,
        "review": review,
        "next_step": next_step,
        "summary": (
            f"On {branch}, {ahead_text} commit(s) ahead of {default}. {next_step}"
        ),
    }
