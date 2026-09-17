# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `SessionStart` hook -- position, derived and injected.

"Session starts cold; the agent has no idea where the work stands" is
§07's framing, and this hook is the fix: derive position fresh from git,
the plan file `save_plan.py` writes, `.canon/config.json`, and GitHub,
then inject it as one line of `additionalContext`. Nothing here is
stored -- every fact is recomputed on every invocation, exactly matching
Invariant II ("position is derived, never stored"). This replaces
CoDev's `restore_position` hook *and its state file*.

Scoped exactly to what docs/plan.md §07's `SessionStart` row names:
branch, plan status, diff size, and PR/check state (plus the configured
verify command, a cheap addition). Review state and the rest of
`canon_position`'s eventual scope (§08) are a later, Phase 1 concern.

Plan *status* alone turned out to be the wrong half of that row. §06
saves the plan into the repository so intent outlives the conversation
that produced it, and a session starting cold was being told that intent
existed without being told what it was -- so the position line also
carries the plan's definition of done and its non-goals, capped. That is
what makes clearing a session, or surviving a compaction, non-destructive
rather than merely survivable.

When `source == "compact"`, this hook also appends a recap: commits since
the default branch, the last logged `Stop` result, and the plan's
`## Open questions`. §07 originally described this as a separate
`PreCompact`/`PostCompact` hook pair -- confirmed directly against Claude
Code's real hook set, no such pair exists there, and `SessionStart` firing
again with `source: "compact"` is the only signal compaction leaves.
Codex does document a separate `PreCompact`/`PostCompact` pair, but also
documents the same `source: "compact"` value on its own `SessionStart`
(not independently confirmed which actually fires in practice -- see
docs/codex-hook-surface.md), so this hook is written to need only the
mechanism both platforms are documented to share, rather than depend on
an event pair this repo has not confirmed exists on every platform it
runs on. Everything recapped already lives in a file (the plan, git
history, `.canon/hooks/decisions.jsonl`), so nothing needed capturing
*before* compaction either way.

It also carries §07's notebook setup check: a repository tracking
`.ipynb` with neither `nbstripout` nor `jupytext` configured is told so,
once per session, with the fix -- recommended, never installed.

Every piece degrades independently and silently: a missing plan file, a
failed git command, or a missing/unauthenticated/offline `gh` each drop
only their own piece of the message, never the whole thing. This hook
only ever adds context -- it cannot block a session from starting and
does not try to.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import _common
import _config
import plan_header

_BULLET_MARKERS = ("- ", "* ", "+ ")
# Enough for the three or four non-goals a well-written plan carries,
# and short enough that a plan with fifteen cannot dominate the message
# every session starts with. The plan's path is in the same sentence,
# so the cap costs a reader one file open, never the information.
_MAX_NON_GOAL_CHARS = 280
_GH_TIMEOUT_SECONDS = 15
_PASSING_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_FAILING_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}


def _plan_relative_path(branch: str) -> Path:
    # `plan_header.branch_plan_relative`, not the plain
    # `.canon/plans/<branch>.md` formula: a `features/<x>` branch's plan
    # is saved at `.canon/plans/branches/features/<x>.md` instead, to
    # avoid colliding with a feature plan of the same slug (see
    # plan_header.py's module docstring).
    return Path(plan_header.branch_plan_relative(branch))


def _read_plan(root: Path, branch: str) -> tuple[dict[str, str], dict[str, str]] | None:
    """The saved plan's `(header, sections)`, or None if there is none to
    read.

    Every caller handles None on its own, so an absent or unreadable plan
    drops exactly the fragments derived from it and nothing else -- the
    independent-degradation property this hook's module docstring makes a
    promise of.
    """
    try:
        text = (root / _plan_relative_path(branch)).read_text(encoding="utf-8")
    except OSError:
        return None
    header, body = _common.plan_header_and_body(text)
    return header, _common.plan_sections(body)


def _plan_status(root: Path, branch: str) -> str:
    relative_path = _plan_relative_path(branch)
    plan = _read_plan(root, branch)
    if plan is None:
        return f"none saved for this branch yet (would be {relative_path})"
    return f"{plan[0].get('status') or 'unknown'} ({relative_path})"


def _collapse(text: str) -> str:
    """One line, single-spaced -- the position line is a sentence, and a
    wrapped markdown bullet would otherwise break it across lines."""
    return " ".join(text.split())


def _bullet_text(line: str) -> str | None:
    """The text of a markdown bullet, or None if this line isn't one."""
    stripped = line.strip()
    for marker in _BULLET_MARKERS:
        if stripped.startswith(marker):
            return stripped[len(marker) :].strip()
    return None


def _terminate(text: str) -> str:
    """`text` ending in exactly one sentence terminator.

    The material here is human-written plan prose: a non-goal usually
    ends in a period already, and a bullet that wrapped mid-clause ends
    in a comma. Terminating unconditionally produces "the public API.."
    and "the module,.", which read as typos in the one message every
    session starts with.
    """
    body = text.rstrip(" ,;:")
    return body if body.endswith((".", "!", "?", "…")) else f"{body}."


def _non_goal_items(section: str) -> list[str]:
    """`## Non-goals` as a flat list of terminated items.

    Each bullet is one item; a continuation line under a bullet is
    dropped rather than joined, because this is a summary and the plan's
    own path travels beside it. A section with no bullets at all becomes
    a single item, so non-goals written as a paragraph are carried
    rather than silently lost.

    Items are terminated here rather than joined with a separator
    because a non-goal is a sentence and routinely contains a semicolon
    or comma of its own -- "don't rewrite the module; the bug is in the
    index" joined with "; " is unreadable and, worse, ambiguous about
    where one non-goal ends and the next begins.
    """
    items = [
        _terminate(_collapse(bullet))
        for line in section.splitlines()
        if (bullet := _bullet_text(line))
    ]
    if items:
        return items
    prose = _collapse(section)
    return [_terminate(prose)] if prose else []


def _fit(text: str) -> str:
    """`text` capped at the budget, cut at a word boundary."""
    if len(text) <= _MAX_NON_GOAL_CHARS:
        return text
    head = text[:_MAX_NON_GOAL_CHARS]
    return f"{head.rsplit(' ', 1)[0] or head}…"


def _non_goals_summary(section: str, relative_path: Path) -> str | None:
    """The non-goals flattened to one sentence and capped.

    Whole items are kept until the budget is spent and the rest are
    counted, so a non-goal is never shown half-written -- a truncated
    "don't rewrite the module" reads as a different instruction from the
    one the plan gave. The single-item case is the one exception and is
    cut at a word boundary, since a non-goals section written as one
    long paragraph would otherwise ignore the budget entirely.
    """
    items = _non_goal_items(section)
    if not items:
        return None
    kept: list[str] = []
    used = 0
    for item in items:
        cost = len(item) + (1 if kept else 0)
        if kept and used + cost > _MAX_NON_GOAL_CHARS:
            break
        kept.append(item)
        used += cost
    summary = _fit(kept[0]) if len(kept) == 1 else " ".join(kept)
    remaining = len(items) - len(kept)
    return f"{summary} (+{remaining} more in {relative_path})" if remaining else summary


def _sentence(label: str, text: str) -> str:
    """`label: text`, terminated exactly once. See `_terminate`."""
    return f"{label}: {_terminate(text)}"


def _plan_intent(root: Path, branch: str) -> list[str]:
    """The saved plan's definition of done and its non-goals, as position
    line sentences.

    docs/plan.md §06 writes the plan into the repository precisely so
    intent outlives the conversation that produced it -- but until this,
    the hook injected only its *status*, so a session that compacted,
    restarted, or was deliberately cleared was told intent existed
    without being told what it was, and had to re-read the file or
    proceed without it.

    `scope:` is deliberately not included. `check_scope` reports a
    departure at the moment it happens, which is more use than a list of
    globs read once at session start, and this message is the one every
    session pays for.
    """
    plan = _read_plan(root, branch)
    if plan is None:
        return []
    header, sections = plan
    parts: list[str] = []
    done = _collapse(header.get("done", ""))
    if done:
        parts.append(_sentence("Done", done))
    non_goals = _non_goals_summary(
        sections.get("non-goals", ""), _plan_relative_path(branch)
    )
    if non_goals:
        parts.append(_sentence("Non-goals", non_goals))
    return parts


def _verify_status(root: Path) -> str:
    config = _config.load_config(root)
    if config is not None and _config.has_verification_signal(config):
        return f"`{config['verify']}`"
    return "not configured yet"


def _diff_summary(root: Path, base: str | None) -> str | None:
    if base is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "diff", "--shortstat", f"{base}..HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    stat = completed.stdout.strip()
    return stat or "no changes yet"


def _check_summary(rollup: Any) -> str | None:
    if not isinstance(rollup, list) or not rollup:
        return None
    passing = failing = pending = 0
    for entry in rollup:
        if not isinstance(entry, dict):
            continue
        state = str(entry.get("conclusion") or entry.get("state") or "").upper()
        if state in _PASSING_CONCLUSIONS:
            passing += 1
        elif state in _FAILING_CONCLUSIONS:
            failing += 1
        else:
            pending += 1
    parts = []
    if passing:
        parts.append(f"{passing} passing")
    if failing:
        parts.append(f"{failing} failing")
    if pending:
        parts.append(f"{pending} pending")
    return ", ".join(parts) if parts else None


def _pr_status(root: Path) -> str:
    try:
        completed = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                "--json",
                "number,url,state,statusCheckRollup",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown (gh unavailable)"
    if completed.returncode != 0:
        return "none open for this branch"
    try:
        data = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return "unknown (unexpected gh output)"
    if not isinstance(data, dict):
        return "unknown (unexpected gh output)"
    number = data.get("number")
    state = str(data.get("state", "")).lower() or "unknown"
    checks = _check_summary(data.get("statusCheckRollup"))
    header = f"#{number} ({state})" if number else f"({state})"
    return f"{header}: {checks}" if checks else header


_JUPYTEXT_CONFIG_NAMES = ("jupytext.toml", ".jupytext.toml", "jupytext.yml")
_NOTEBOOK_CHECK_LIMIT = 1


def _tracked_notebook(root: Path) -> str | None:
    """One tracked `.ipynb`, or None. Asks git rather than walking the
    tree, so an untracked scratch notebook never triggers this."""
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "*.ipynb"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    for name in completed.stdout.split("\0"):
        if name.strip():
            return name.strip()
    return None


def _readable_form_configured(root: Path) -> bool:
    """Whether an `nbstripout` git filter or a jupytext config is set up."""
    try:
        attributes = (root / ".gitattributes").read_text(encoding="utf-8")
    except OSError:
        attributes = ""
    for line in attributes.splitlines():
        if ".ipynb" in line and "filter=" in line:
            return True
    if any((root / name).is_file() for name in _JUPYTEXT_CONFIG_NAMES):
        return True
    try:
        return "[tool.jupytext" in (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False


def _notebook_setup_note(root: Path) -> str | None:
    """docs/plan.md §07: "Canon's setup check notices `.ipynb` tracked
    with neither configured and says so once, with the fix. It
    recommends and never installs, the same rule as branch protection."

    "Once" is per session, which is what `SessionStart` gives for free.
    """
    notebook = _tracked_notebook(root)
    if notebook is None or _readable_form_configured(root):
        return None
    return (
        f"Notebooks: this repository tracks .ipynb files (e.g. {notebook}) with "
        "neither nbstripout nor jupytext configured, so their diffs carry "
        "execution_count churn and re-serialised output. Canon extracts code "
        "cells itself for review, but a git filter (nbstripout) or a jupytext "
        "pairing is the real fix. Recommend it if it comes up -- never install "
        "it."
    )


def _position_line(
    root: Path, branch: str, default_branch: str, base: str | None
) -> str:
    parts = [f"Canon position: branch `{branch}`."]
    parts.append(f"Plan: {_plan_status(root, branch)}.")
    parts.extend(_plan_intent(root, branch))
    parts.append(f"Verify: {_verify_status(root)}.")

    diff = _diff_summary(root, base)
    if diff is not None:
        parts.append(f"Diff vs `{default_branch}`: {diff}.")

    parts.append(f"PR: {_pr_status(root)}.")
    note = _notebook_setup_note(root)
    if note is not None:
        parts.append(note)
    return " ".join(parts)


def _recent_commits(root: Path, base: str | None) -> str | None:
    if base is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "log", "--oneline", "-n", "10", f"{base}..HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    log = completed.stdout.strip()
    return log.replace("\n", "; ") if log else None


def _last_verification(root: Path) -> str | None:
    record = _common.last_decision(root, "stop.py")
    if record is None:
        return None
    decision = record.get("decision", "unknown")
    timestamp = record.get("timestamp", "")
    reason = record.get("reason", "")
    line = f"{decision} at {timestamp}" if timestamp else str(decision)
    return f"{line} — {reason}" if reason else line


def _open_questions(root: Path, branch: str) -> str | None:
    plan = _read_plan(root, branch)
    return plan[1].get("open questions") or None if plan else None


def _compaction_recap(
    root: Path, branch: str, default_branch: str, base: str | None
) -> str:
    lines = [
        "Post-compaction recap (this survives the summariser because it "
        "was never only in the transcript):"
    ]
    commits = _recent_commits(root, base)
    lines.append(f"Decisions since `{default_branch}`: {commits or 'none yet'}")
    verification = _last_verification(root)
    lines.append(f"Last verification: {verification or 'none logged yet'}")
    open_questions = _open_questions(root, branch)
    if open_questions:
        lines.append(f"Open questions:\n{open_questions}")
    return "\n".join(lines)


def main() -> None:
    payload = _common.read_payload()
    root = _common.repo_root(payload)
    branch = _common.current_branch(root) or "unknown"
    default_branch = _common.default_branch(root)
    base = _common.merge_base(root, default_branch)

    message = _position_line(root, branch, default_branch, base)
    if payload is not None and payload.get("source") == "compact":
        message += "\n\n" + _compaction_recap(root, branch, default_branch, base)

    _common.context("SessionStart", message)


if __name__ == "__main__":
    _common.fail_open(main)()
