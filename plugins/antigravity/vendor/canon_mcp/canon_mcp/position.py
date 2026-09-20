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

from ._config import has_verification_signal, interaction_mode, load_config
from ._gh import pr_list_by_head, pr_view
from ._git import (
    branch_names,
    commits_ahead,
    current_branch,
    default_branch,
    head_sha,
    merge_base,
    merged_branch_names,
)
from ._plan import branch_plan_relative, read_plan_file, resolve_parent
from ._steps import annotate, parse_steps, summarize
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


def _build_feature(
    root: Path, plan: dict[str, Any] | None, default: str
) -> dict[str, Any] | None:
    """Where this branch sits in its feature plan, or None if it has no
    `parent:` -- docs/plan.md §06's "which step am I on?", derived.

    Every fact is recomputed here: the parent's `## Steps` list, which
    branches exist, which pull requests merged. Nothing is stored, so
    nothing can be stale.
    """
    if plan is None:
        return None
    parent_path = plan["header"].get("parent")
    if not parent_path:
        return None
    parent = resolve_parent(root, parent_path)
    if parent is None:
        return None
    steps = parse_steps(parent["sections"].get("steps", ""))
    if not steps:
        return None
    annotated = annotate(
        steps,
        branch_names(root),
        pr_list_by_head(root),
        merged_branch_names(root, default),
    )
    return summarize(parent["path"], annotated)


def _feature_sentence(feature: dict[str, Any] | None) -> str:
    """The feature's position as one appendable clause, or ""."""
    if feature is None:
        return ""
    current = feature.get("current")
    total = feature.get("total")
    if current is None:
        return f" All {total} steps of {feature['path']} have landed."
    label = current.get("slug") or current.get("description")
    return f" This is step {current['index']} of {total} in {feature['path']}: {label}."


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


def _next_feature_step(feature: dict[str, Any] | None) -> str:
    """What to start next once this branch has landed, if its feature
    plan names a further step."""
    if feature is None:
        return ""
    current = feature.get("current")
    if current is None:
        return f"; every step of {feature['path']} has landed"
    label = current.get("slug") or current.get("description")
    return (
        f"; next in {feature['path']} is step {current['index']} "
        f"of {feature['total']}: {label}"
    )


def _next_step(
    verify_ok: bool,
    plan: dict[str, Any] | None,
    pr: dict[str, Any] | None,
    review: dict[str, Any],
    feature: dict[str, Any] | None = None,
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
        done = f"PR #{number} is {state} -- nothing further to do on this branch"
        return done + _next_feature_step(feature)
    failing, incomplete = _check_state(pr)
    if failing:
        return f"fix the failing check ({failing}) on PR #{number}"
    if incomplete:
        return f"wait for CI to finish ({incomplete}) on PR #{number}"
    verdict = review.get("verdict")
    if verdict is None:
        names = review.get("reviewers_called_for") or ["reviewer"]
        label = " and ".join(names)
        plural = "s" if len(names) > 1 else ""
        return f"dispatch the {label} subagent{plural} for PR #{number}"
    if review.get("stale"):
        # Not "review it all again": the `review` skill asks for the delta
        # since the commit that reviewer last saw, alongside the full
        # range, because a fix that breaks something already passed is
        # invisible when the whole diff is re-read from scratch. These two
        # instructions have to agree, or the skill and this sentence send
        # the agent in different directions on the same signal.
        return (
            f"re-review PR #{number} -- HEAD has moved since the last "
            "verdict, so the reviewer needs the delta since the commit it "
            "last saw as well as the full range"
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
    plan = read_plan_file(root, branch_plan_relative(branch))
    config = load_config(root)
    verify_ok = has_verification_signal(config)
    mode = interaction_mode(config)
    # No PR to ask about while standing on the default branch itself.
    pr = pr_view(root, branch) if branch != default else None
    review = build_review(root)
    feature = _build_feature(root, plan, default)
    next_step = _next_step(verify_ok, plan, pr, review, feature)
    ahead_text = str(ahead) if ahead is not None else "an unknown number of"
    return {
        "branch": branch,
        "default_branch": default,
        "base": base,
        "head": head,
        "commits_ahead": ahead,
        "verify_configured": verify_ok,
        "mode": mode,
        "plan": _plan_summary(plan),
        "feature": feature,
        "pull_request": pr,
        "review": review,
        "next_step": next_step,
        "summary": (
            f"On {branch}, {ahead_text} commit(s) ahead of {default}."
            f"{_feature_sentence(feature)} {next_step}"
        ),
    }
