# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `Stop` hook — the verification gate.

Invariant III ("nothing ships on the agent's own word") is a precondition:
if this repository has no configured verification command, Canon stays
inert rather than operating unverified (see docs/plan.md §07, "No signal,
no Canon"). So this hook does one of two things on every `Stop` event:

- No `verify` command in `.canon/config.json` yet: block once per
  session to surface the first-run question -- proposing whatever
  `_config.suggest_verify_command` inferred, or asking outright when
  nothing was inferred -- then allow silently on every later `Stop` in
  the same session. A `Stop` hook has no "ask" permission decision and no
  TTY-based degradation the way `PreToolUse` does; `block` is the only
  mechanism that reliably puts text in front of Claude, which is then
  expected to relay the question to the developer and, once answered,
  write `.canon/config.json` itself -- a plain file edit, not a new tool.
- A `verify` command is configured: run it and block on a red result,
  attaching the failure so the claim "tests pass" is something the
  harness checked rather than something the agent asserted.

The one state this hook is allowed to remember, per `_common.py`'s module
docstring and `AGENTS.md`: a same-session marker (so the first-run
question is asked once, not on every `Stop`) and a consecutive-refusal
counter (so a run of red results doesn't block forever). Both live under
the `scratchpad_dir` Claude Code includes in the `Stop` payload -- never
under the repository -- and both fail open to their empty state if that
field is missing.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import _common
import _config

_MAX_CONSECUTIVE_REFUSALS = 3
_VERIFY_TIMEOUT_SECONDS = 300
_OUTPUT_TAIL_CHARS = 4000

_PROMPTED_MARKER_NAME = "verify_prompted"
_REFUSAL_COUNTER_NAME = "consecutive_refusals"


def _has_been_prompted(state_dir: Path | None) -> bool:
    return state_dir is not None and (state_dir / _PROMPTED_MARKER_NAME).exists()


def _mark_prompted(state_dir: Path | None) -> None:
    if state_dir is None:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / _PROMPTED_MARKER_NAME).write_text("", encoding="utf-8")
    except OSError:
        pass


def _read_refusal_count(state_dir: Path | None) -> int:
    if state_dir is None:
        return 0
    try:
        text = (state_dir / _REFUSAL_COUNTER_NAME).read_text(encoding="utf-8")
        return int(text.strip())
    except (OSError, ValueError):
        return 0


def _write_refusal_count(state_dir: Path | None, count: int) -> None:
    if state_dir is None:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / _REFUSAL_COUNTER_NAME).write_text(str(count), encoding="utf-8")
    except OSError:
        pass


def _first_run_reason(root: Path) -> str:
    suggestion = _config.suggest_verify_command(root)
    ask = (
        f"A likely candidate, inferred from this repository: `{suggestion}`."
        if suggestion
        else "Nothing could be inferred -- ask what command should pass "
        "before a turn ends (for example `pytest`, `npm test`, or "
        "`make check`)."
    )
    return (
        "Canon has no verification command configured for this repository "
        "yet, and stays inert until it does. " + ask + " Confirm it with "
        'the developer, then save it by writing {"verify": "<command>"} '
        "to .canon/config.json."
    )


def _run_verification(root: Path, command: str) -> tuple[bool, str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return False, f"Could not parse the configured verify command: {exc}"
    if not argv:
        return False, "The configured verify command is empty."
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
        return False, f"`{command}` timed out after {_VERIFY_TIMEOUT_SECONDS}s."
    except OSError as exc:
        return False, f"Could not run `{command}`: {exc}"
    if completed.returncode == 0:
        return True, ""
    output = (completed.stdout or "") + (completed.stderr or "")
    return (
        False,
        f"`{command}` exited {completed.returncode}:\n{output[-_OUTPUT_TAIL_CHARS:]}",
    )


def main() -> None:
    payload = _common.read_payload()
    root = _common.repo_root(payload)
    state_dir = _common.state_dir(payload)
    config = _config.load_config(root)

    if config is None or not _config.has_verification_signal(config):
        if _has_been_prompted(state_dir):
            _common.allow()
            return
        _mark_prompted(state_dir)
        _common.block(_first_run_reason(root))
        return

    command = config["verify"]
    passed, detail = _run_verification(root, command)
    if passed:
        _write_refusal_count(state_dir, 0)
        _common.log_decision(root, "stop.py", "allow", reason=f"`{command}` passed")
        _common.allow()
        return

    refusals = _read_refusal_count(state_dir) + 1
    if refusals > _MAX_CONSECUTIVE_REFUSALS:
        _write_refusal_count(state_dir, 0)
        _common.log_decision(
            root,
            "stop.py",
            "allow",
            reason=f"giving up after {refusals} consecutive failures: {detail}",
        )
        _common.allow()
        return
    _write_refusal_count(state_dir, refusals)
    _common.log_decision(root, "stop.py", "block", reason=detail)
    _common.block(detail)


if __name__ == "__main__":
    _common.fail_open(main)()
