# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `Stop` hook -- the verification gate (Antigravity port).

Invariant III ("nothing ships on the agent's own word") is a precondition:
if this repository has no configured verification command, Canon stays
inert rather than operating unverified (see docs/plan.md §07, "No signal,
no Canon").

Under Antigravity's lifecycle protocol, the Stop decision contract is:
- To allow the agent to stop: emit `{}` (empty object) and exit 0.
- To block stopping and continue the turn: emit
  `{"decision": "continue", "reason": "..."}` and exit 0.

This hook handles:
1. No `verify` command in `.canon/config.json`: continues turn once per session
   to surface the first-run question, then allows stopping on subsequent stops.
2. A `verify` command is configured: runs repo verification with a 300s timeout.
   - On pass: resets consecutive refusals, logs allow, and emits `{}`.
   - On failure: increments consecutive refusals. If cap (3) is exceeded,
     gives up, resets counter, logs allow, and emits `{}`. Otherwise emits
     `{"decision": "continue", "reason": detail}`.
3. State (refusal counter and verify prompt marker) is stored exclusively under
   `artifactDirectoryPath / conversationId / canon`, never in the repository.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_hooks_dir = str(Path(__file__).resolve().parent)
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

import _common_agy as _common  # noqa: E402
import _config  # noqa: E402

_MAX_CONSECUTIVE_REFUSALS = 3
_VERIFY_TIMEOUT_SECONDS = 300
_OUTPUT_TAIL_CHARS = 4000

_PROMPTED_MARKER_NAME = "verify_prompted"
_CONFIG_FAULT_MARKER_NAME = "verify_config_fault_prompted"
_REFUSAL_COUNTER_NAME = "consecutive_refusals"


def _stop_hook_active(payload: dict[str, Any] | None) -> bool:
    """Whether the harness reports this turn is already continuing.
    Checks Antigravity's `executionNum > 1` and fallback `stop_hook_active`."""
    if not payload:
        return False
    if payload.get("stop_hook_active"):
        return True
    execution_num = payload.get("executionNum")
    if isinstance(execution_num, int) and execution_num > 1:
        return True
    return False


def _has_been_prompted(
    state_dir: Path | None,
    stop_hook_active: bool,
    marker_name: str = _PROMPTED_MARKER_NAME,
) -> bool:
    if state_dir is None:
        return True
    return (state_dir / marker_name).exists()


def _mark_prompted(
    state_dir: Path | None,
    marker_name: str = _PROMPTED_MARKER_NAME,
) -> None:
    if state_dir is None:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / marker_name).write_text("", encoding="utf-8")
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


def _should_give_up(
    state_dir: Path | None, stop_hook_active: bool, refusals: int
) -> bool:
    """Whether a red result should be let through rather than blocked again.

    With a scratchpad, that's the counter reaching its cap. Without one
    there is no counter, so we fail open immediately to avoid infinite
    refusal loops.
    """
    if state_dir is None:
        return True
    return refusals > _MAX_CONSECUTIVE_REFUSALS


def _give_up_reason(state_dir: Path | None, refusals: int, detail: str) -> str:
    if state_dir is None:
        return (
            "giving up: no session state to count refusals with, and the "
            f"harness reports this turn already continued once -- {detail}"
        )
    return f"giving up after {refusals} consecutive failures: {detail}"


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


def _configuration_fault_reason(command: str, source: str, detail: str) -> str:
    return (
        f"The verify command in {source} (`{command}`) cannot be "
        f"run as configured: {detail} This is a configuration problem, not "
        f"a failing check -- relay it to the developer so they can fix "
        f"{source}. Canon will not block on this again this "
        "session, but it also cannot verify anything until it's fixed."
    )


def _handle_configuration_fault(
    root: Path,
    state_dir: Path | None,
    stop_hook_active: bool,
    command: str,
    source: str,
    detail: str,
) -> None:
    reason = _configuration_fault_reason(command, source, detail)
    if _has_been_prompted(
        state_dir, stop_hook_active, marker_name=_CONFIG_FAULT_MARKER_NAME
    ):
        _common.log_decision(
            root,
            "stop.py",
            "allow",
            reason=f"configuration fault already surfaced this session: {reason}",
        )
        _common.pass_stop()
        return
    _mark_prompted(state_dir, marker_name=_CONFIG_FAULT_MARKER_NAME)
    _common.log_decision(root, "stop.py", "continue", reason=reason)
    _common.continue_turn(reason)


@_common.fail_open(fallback_fn=_common.pass_stop)
def main() -> None:
    payload = _common.read_payload()
    if not payload:
        _common.pass_stop()
        return

    if not _common.has_workspace(payload):
        _common.pass_stop()
        return

    state_dir = _common.state_dir(payload)
    if state_dir is None:
        _common.pass_stop()
        return

    root = _common.repo_root(payload)
    if not root.is_dir():
        _common.pass_stop()
        return

    stop_hook_active = _stop_hook_active(payload)
    config = _config.load_config(root)

    if config is None or not _config.has_verification_signal(config):
        if _has_been_prompted(state_dir, stop_hook_active):
            _common.pass_stop()
            return
        _mark_prompted(state_dir)
        _common.continue_turn(_first_run_reason(root))
        return

    branch = _common.current_branch(root)
    command = _config.resolve_verify_command(root, branch, config)
    if command is None:
        _common.pass_stop()
        return

    problem = _config.verify_command_problem(command)
    if problem is not None:
        source = _config.verify_command_source(root, branch, config)
        _handle_configuration_fault(
            root, state_dir, stop_hook_active, command, source, problem
        )
        return

    result = _common.run_command(command, cwd=root, timeout=_VERIFY_TIMEOUT_SECONDS)
    if result.passed:
        _write_refusal_count(state_dir, 0)
        _common.log_decision(root, "stop.py", "allow", reason=f"`{command}` passed")
        _common.pass_stop()
        return

    if result.configuration_fault:
        source = _config.verify_command_source(root, branch, config)
        _handle_configuration_fault(
            root, state_dir, stop_hook_active, command, source, result.detail
        )
        return

    refusals = _read_refusal_count(state_dir) + 1
    if _should_give_up(state_dir, stop_hook_active, refusals):
        _write_refusal_count(state_dir, 0)
        _common.log_decision(
            root,
            "stop.py",
            "allow",
            reason=_give_up_reason(state_dir, refusals, result.detail),
        )
        _common.pass_stop()
        return

    _write_refusal_count(state_dir, refusals)
    _common.log_decision(root, "stop.py", "continue", reason=result.detail)
    _common.continue_turn(result.detail)


if __name__ == "__main__":
    main()
