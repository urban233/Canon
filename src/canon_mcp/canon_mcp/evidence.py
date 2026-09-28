# SPDX-License-Identifier: BSD-3-Clause
"""`canon_evidence` -- whether this commit is green, and where that was
established.

Per docs/plan.md §08's "Why there is no evidence store": a pushed
commit's answer comes from CI, content-addressed by its own SHA; an
unpushed commit has no such record, so the honest answer is a fresh
local re-run, never a cached guess. This module computes both paths
fresh on every call -- nothing here is stored.

`_run_local_check` is `plugins/claude/hooks/_common.py`'s
`run_command`, ported (not imported -- see `_git.py`'s module
docstring for why hooks and this package don't share a dependency
edge): same `shlex.split`, same 300s timeout, same 4000-char output
tail on failure, and the same three-way split between "passed",
"executed and failed", and "could not be run as configured at all" --
see `_config.verify_command_problem` and the `configuration_fault` flag
below. A command this server cannot run is not evidence the repository
is red; `build_evidence` reports it the same way it reports "not
configured yet" -- `green: None` plus a `message` -- rather than as
`green: False`, which `ship.py` would read as a real failure.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ._config import (
    has_verification_signal,
    load_config,
    resolve_verify_command,
    ship_evidence_config,
    verify_command_problem,
    verify_command_source,
)
from ._gh import ci_runs_for_commit
from ._git import current_branch, full_head_sha, head_tree, is_pushed

_VERIFY_TIMEOUT_SECONDS = 300
_OUTPUT_TAIL_CHARS = 4000


def _run_local_check(root: Path, command: str) -> tuple[bool, str, bool]:
    """Run `command` with no shell and report the result.

    Returns `(passed, detail, configuration_fault)` -- see
    `plugins/claude/hooks/_common.py`'s `run_command`, which this
    mirrors exactly. `configuration_fault` is True when the command
    could not be parsed or its binary is not on `PATH`, and False for a
    command that ran and either timed out or exited non-zero.
    `build_evidence` uses the flag to report a configuration fault as
    `green: None`, never as `green: False`.

    The compound-command case is caught earlier, by
    `verify_command_problem`, before this function is ever called; the
    `ValueError` branch here is the same defense in depth
    `shell_metacharacter`'s docstring describes.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return False, f"Could not parse the configured verify command: {exc}", True
    if not argv:
        return False, "The configured verify command is empty.", True
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"`{command}` timed out after {_VERIFY_TIMEOUT_SECONDS}s.", False
    except OSError as exc:
        return False, f"Could not run `{command}`: {exc}", True
    if completed.returncode == 0:
        return True, "", False
    output = (completed.stdout or "") + (completed.stderr or "")
    return (
        False,
        f"`{command}` exited {completed.returncode}:\n{output[-_OUTPUT_TAIL_CHARS:]}",
        False,
    )


def _latest_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The run with the latest `createdAt`, or None for an empty list.

    `gh run list` doesn't document a guaranteed sort order, so this
    picks explicitly rather than trusting list order.
    """
    if not runs:
        return None
    return max(runs, key=lambda run: run.get("createdAt") or "")


def build_evidence(root: Path) -> dict[str, Any]:
    """Whether the current HEAD is green, and where that was
    established: CI for a pushed commit, a fresh local re-run for one
    that isn't -- plus, when the repository declares one, whether its
    ship evidence was produced for exactly this tree."""
    evidence = _build_head_evidence(root)
    ship = ship_evidence(root, load_config(root))
    if ship is not None:
        evidence["ship_evidence"] = ship
    return evidence


def ship_evidence(root: Path, config: dict[str, Any] | None) -> dict[str, Any] | None:
    """The declared ship-evidence result, checked against HEAD's tree, or
    None when the repository declares none.

    docs/decisions/0010-ship-evidence-is-verified-not-stored.md: Canon
    never runs `command` -- the evidence it names is too slow, or needs a
    display, which is exactly why neither CI nor the `Stop` hook covers
    it. It reads the file the repository's command wrote and checks the
    binding: the recorded `tree` must be HEAD's tree, the run must not
    have been on a dirty tree, and it must have passed. `status` is one
    of `passed`, `missing`, `malformed`, `stale`, `dirty` or `failed`.
    What this verifies is the binding, not the honesty -- a hand-written
    file passes too; see the record's Consequences.
    """
    spec = ship_evidence_config(config)
    if spec is None:
        return None
    if "problem" in spec:
        return {"status": "malformed", "detail": spec["problem"]}
    report: dict[str, Any] = {"command": spec["command"], "result": spec["result"]}

    def verdict(status: str, detail: str) -> dict[str, Any]:
        return {**report, "status": status, "detail": detail}

    try:
        raw = (root / spec["result"]).read_text(encoding="utf-8")
    except OSError:
        return verdict("missing", f"`{spec['result']}` does not exist yet")
    except UnicodeDecodeError:
        return verdict("malformed", f"`{spec['result']}` is not UTF-8 JSON")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return verdict("malformed", f"`{spec['result']}` is not JSON")
    if not isinstance(data, dict):
        return verdict("malformed", f"`{spec['result']}` is not a JSON object")
    tree, dirty, passed = data.get("tree"), data.get("dirty"), data.get("passed")
    if (
        not isinstance(tree, str)
        or not tree
        or not isinstance(dirty, bool)
        or not isinstance(passed, bool)
    ):
        return verdict(
            "malformed",
            f"`{spec['result']}` needs a string `tree` and booleans `dirty` "
            "and `passed`",
        )
    report["tree"] = tree
    if isinstance(data.get("checks"), list):
        report["checks"] = data["checks"]
    current = head_tree(root)
    report["head_tree"] = current
    if current is None or len(tree) < 7 or not current.startswith(tree):
        return verdict("stale", "it was produced for a different tree than HEAD's")
    if dirty:
        return verdict("dirty", "it was produced on a working tree with changes")
    if not passed:
        return verdict("failed", "it ran against HEAD's tree and did not pass")
    return verdict("passed", "it ran against HEAD's tree and passed")


def _build_head_evidence(root: Path) -> dict[str, Any]:
    sha = full_head_sha(root)
    if sha is not None and is_pushed(root, sha):
        runs = ci_runs_for_commit(root, sha) or []
        latest = _latest_run(runs)
        green = (
            latest is not None
            and latest.get("status") == "completed"
            and latest.get("conclusion") == "success"
        )
        return {
            "head": sha,
            "pushed": True,
            "source": "ci",
            "runs": runs,
            "green": green if latest is not None else None,
        }

    config = load_config(root)
    if not has_verification_signal(config):
        return {
            "head": sha,
            "pushed": False,
            "source": None,
            "green": None,
            "message": "not pushed, and no verify command configured yet",
        }
    branch = current_branch(root)
    command = resolve_verify_command(root, branch, config)
    if command is None:  # pragma: no cover - has_verification_signal implies one
        return {
            "head": sha,
            "pushed": False,
            "source": None,
            "green": None,
            "message": "not pushed, and no verify command configured yet",
        }

    # A command already on disk that cannot be run as configured (most
    # often: compound) is a configuration fault, caught before
    # `_run_local_check` ever calls `subprocess.run` -- reported the same
    # way as "not configured yet" rather than as a failed check. Named
    # after `verify_command_source`, not hard-coded to
    # `.canon/config.json`, since the command may have come from a plan
    # header instead -- naming the wrong file sends a human to edit it.
    problem = verify_command_problem(command)
    if problem is not None:
        command_source = verify_command_source(root, branch, config)
        return {
            "head": sha,
            "pushed": False,
            "source": None,
            "green": None,
            "message": (
                f"the verify command in {command_source} (`{command}`) "
                f"cannot be run as configured: {problem}"
            ),
        }

    passed, detail, configuration_fault = _run_local_check(root, command)
    if configuration_fault:
        # Discovered only at execution time -- typically the named
        # binary is not on `PATH`. Same treatment as the pre-check
        # above, for the same reason: not evidence about the
        # repository's own tests.
        command_source = verify_command_source(root, branch, config)
        return {
            "head": sha,
            "pushed": False,
            "source": None,
            "green": None,
            "message": (
                f"the verify command in {command_source} (`{command}`) "
                f"cannot be run as configured: {detail}"
            ),
        }
    return {
        "head": sha,
        "pushed": False,
        "source": "local_rerun",
        "command": command,
        "green": passed,
        "detail": detail,
    }
