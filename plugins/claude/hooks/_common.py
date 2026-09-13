# SPDX-License-Identifier: BSD-3-Clause
"""Shared plumbing for every Canon hook.

Standard library only, valid under Python 3.9. A hook runs on whatever
`python3` the host machine has, not on a resolved Bazel toolchain, so this
module imports nothing Canon ships and shells out to nothing -- unlike
CoDev's hooks, which resolved a `codev` CLI on every invocation and, by
CoDev's own decision log, found nothing to run 508 times out of 1,112. A
guardrail that depends on external resolution is a guardrail that silently
does nothing on exactly the machines it can't resolve on; this module has
no such dependency to fail.

Every Canon gate fails open (see `fail_open`): a guardrail that errors must
never block work. And Canon writes no repository state -- the one file this
module writes, `.canon/hooks/decisions.jsonl`, is a gitignored local
diagnostic that is never read back to make a decision. The single permitted
exception is a `Stop` hook's consecutive-refusal counter, which lives in the
session's `scratchpad_dir`, never in the repository, and is documented on
that hook rather than here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_DECISIONS_LOG_RELATIVE = ".canon/hooks/decisions.jsonl"
_GIT_TIMEOUT_SECONDS = 10


def read_payload() -> dict[str, Any] | None:
    """Parse the hook's JSON input from stdin.

    Returns None on anything malformed -- empty stdin, invalid JSON, or a
    top-level value that isn't an object -- rather than raising. Every
    caller must treat None as "fail open", never as an error to surface.
    """
    raw = sys.stdin.read()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def repo_root(payload: dict[str, Any] | None) -> Path:
    """The repository root the hook should act on.

    Prefers `cwd` from the payload, since that is what Claude Code sets to
    the project directory. Falls back to `git rev-parse --show-toplevel`
    from the current process's own cwd, and finally to `Path.cwd()` itself
    -- this never raises, because a hook that can't find the repo root must
    still be able to fail open rather than crash.
    """
    cwd = None
    if payload:
        raw_cwd = payload.get("cwd")
        if isinstance(raw_cwd, str) and raw_cwd:
            cwd = Path(raw_cwd)
    if cwd is not None:
        return cwd
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode == 0:
            candidate = completed.stdout.strip()
            if candidate:
                return Path(candidate)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path.cwd()


def _run_git(root: Path, *args: str) -> str | None:
    """Run a read-only git command in `root`.

    Returns trimmed stdout, or None on any failure -- git missing, a
    timeout, a non-zero exit, or empty output. Every caller must treat
    None as "couldn't determine this," never as an error to surface.
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def current_branch(root: Path) -> str | None:
    """The current branch name, or None if it can't be determined."""
    return _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")


def default_branch(root: Path) -> str:
    """The repository's default branch, best-effort.

    Reads `origin/HEAD`; falls back to "main" when there's no such remote
    ref -- no remote configured, or it was never set -- rather than
    failing outright.
    """
    ref = _run_git(root, "rev-parse", "--abbrev-ref", "origin/HEAD")
    if ref and ref.startswith("origin/"):
        return ref[len("origin/") :]
    return "main"


def merge_base(root: Path, default_branch_name: str) -> str | None:
    """The short SHA where the current branch diverged from
    `default_branch_name`, or None if that can't be determined."""
    sha = _run_git(root, "merge-base", "HEAD", default_branch_name)
    return sha[:9] if sha else None


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout)


def allow() -> None:
    """PreToolUse: let the tool call proceed with no comment."""
    sys.exit(0)


def ask(reason: str) -> None:
    """PreToolUse: pause for confirmation, with a reason Claude can show."""
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        }
    )
    sys.exit(0)


def deny(reason: str) -> None:
    """PreToolUse: refuse the tool call outright, with a reason.

    Used instead of `ask` wherever a caller cannot tell whether an
    interactive terminal exists -- an `ask` decision silently degrades to
    deny with no explanation when there is none, so a hook that might run
    headless should decide explicitly rather than rely on that fallback.
    """
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )
    sys.exit(0)


def block(reason: str) -> None:
    """Stop: refuse to let the turn end, with a reason handed back to Claude."""
    _emit({"decision": "block", "reason": reason})
    sys.exit(0)


def context(event: str, message: str) -> None:
    """Any event that only wants to add context, never to gate anything."""
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": message,
            }
        }
    )
    sys.exit(0)


def fail_open(main: Callable[[], None]) -> Callable[[], None]:
    """Wrap a hook's entry point so any unhandled exception exits 0 silently.

    Every Canon gate fails open by design (see the module docstring); this
    makes that structural rather than something each hook has to remember
    to catch. A hook that raises without this wrapper would exit non-zero,
    which several events treat as a blocking error -- exactly the opposite
    of what a guardrail that errors should do.
    """

    def wrapped() -> None:
        try:
            main()
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001 - a failing guardrail must not block
            sys.exit(0)

    return wrapped


def log_decision(
    root: Path,
    hook_name: str,
    decision: str,
    *,
    reason: str = "",
) -> None:
    """Append one local, gitignored diagnostic record.

    Never raises: a broken log must never change a hook's own allow/ask/deny
    behavior, and this file is never read back by any hook to decide
    anything -- see the module docstring's no-stored-state rule.
    """
    try:
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hook": hook_name,
            "decision": decision,
            "reason": reason,
        }
        path = root / _DECISIONS_LOG_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass
