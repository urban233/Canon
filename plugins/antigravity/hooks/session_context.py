# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PreInvocation` hook -- position, derived and injected (Antigravity port).

"Session starts cold; the agent has no idea where the work stands" is
§07's framing, and this hook is the fix: derive position fresh from git,
the plan file `save_plan.py` writes, `.canon/config.json`, and GitHub,
then inject it as an ephemeral message in Antigravity's PreInvocation turn:

    {"injectSteps": [{"ephemeralMessage": "..."}]}

Nothing here is stored -- every fact is recomputed on every invocation, exactly
matching Invariant II ("position is derived, never stored").

To avoid prompt bloat, this hook gates execution on `invocationNum == 0`
(or post-compaction). On subsequent turns, it emits `{}` immediately.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_hooks_dir = str(Path(__file__).resolve().parent)
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

import _common_agy as _common  # noqa: E402
import _config  # noqa: E402
import plan_header  # noqa: E402

_PLANS_DIR_RELATIVE = Path(".canon") / "plans"
_BULLET_MARKERS = ("- ", "* ", "+ ")
_MAX_NON_GOAL_CHARS = 280
_GH_TIMEOUT_SECONDS = 15
_PASSING_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_FAILING_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}


def _plan_relative_path(branch: str) -> Path:
    return Path(plan_header.branch_plan_relative(branch))


def _read_plan(root: Path, branch: str) -> tuple[dict[str, str], dict[str, str]] | None:
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
    return " ".join(text.split())


def _bullet_text(line: str) -> str | None:
    stripped = line.strip()
    for marker in _BULLET_MARKERS:
        if stripped.startswith(marker):
            return stripped[len(marker) :].strip()
    return None


def _terminate(text: str) -> str:
    body = text.rstrip(" ,;:")
    return body if body.endswith((".", "!", "?", "…")) else f"{body}."


def _non_goal_items(section: str) -> list[str]:
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
    if len(text) <= _MAX_NON_GOAL_CHARS:
        return text
    head = text[:_MAX_NON_GOAL_CHARS]
    return f"{head.rsplit(' ', 1)[0] or head}…"


def _non_goals_summary(section: str, relative_path: Path) -> str | None:
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
    return f"{label}: {_terminate(text)}"


def _plan_intent(root: Path, branch: str) -> list[str]:
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


def _tracked_notebook(root: Path) -> str | None:
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


@_common.fail_open(fallback_fn=_common.pass_stop)
def main() -> None:
    payload = _common.read_payload()
    if not payload:
        _common.pass_stop()
        return

    invocation_num = payload.get("invocationNum", 0) if payload else 0
    is_compact = (
        payload.get("source") == "compact" or payload.get("isCompacted", False)
        if payload
        else False
    )

    if invocation_num > 0 and not is_compact:
        _common.pass_stop()
        return

    if not _common.has_workspace(payload):
        _common.pass_stop()
        return

    artifact_dir = payload.get("artifactDirectoryPath")
    if not (isinstance(artifact_dir, str) and artifact_dir.strip()):
        _common.pass_stop()
        return

    root = _common.repo_root(payload)
    if not root.is_dir():
        _common.pass_stop()
        return

    branch = _common.current_branch(root) or "unknown"
    default_branch = _common.default_branch(root)
    base = _common.merge_base(root, default_branch)

    message = _position_line(root, branch, default_branch, base)
    if is_compact:
        message += "\n\n" + _compaction_recap(root, branch, default_branch, base)

    _common.inject_context(message)


if __name__ == "__main__":
    main()
