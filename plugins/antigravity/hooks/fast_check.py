# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PostToolUse` hook for an edit -- the fast check (Antigravity port).

docs/plan.md §11 sets out three quality layers at three latencies:
`PostToolUse` as each file is written (cosmetic, no authority), `Stop` at
the end of every turn (blocks the turn), and CI on the pull request
(blocks the merge). Layer one existed only on paper. §11 says it is there
"purely so neither of them ever fails for a reason as trivial as
whitespace" -- and in one session three pull requests failed CI on
`fmt_check` alone, every other check green on all of them. That is
precisely the failure the layer was specified to absorb.

In Antigravity, this runs on `PostToolUse` for `replace_file_content|write_to_file`:
- Purely advisory, cosmetic first quality layer.
- Never blocks or denies (exits 0 with `{}` on clean pass, timeout, or stand down).
- Emits `additionalContext` via `_common.context()` on failure or configuration fault.
- Debounced across edits within 30 seconds (`_DEBOUNCE_SECONDS = 30`).
- Silent on timeout, backing off for 600 seconds (`_TIMEOUT_BACKOFF_SECONDS = 600`).
- Configuration faults are reported once per session.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_hooks_dir = str(Path(__file__).resolve().parent)
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

import _common_agy as _common  # noqa: E402
import _config  # noqa: E402

_EDIT_TOOL_NAMES = (None, "replace_file_content", "write_to_file", "Edit", "Write")

_FAST_CHECK_TIMEOUT_SECONDS = 60
_DEBOUNCE_SECONDS = 30
_TIMEOUT_BACKOFF_SECONDS = 600

_NEXT_RUN_NAME = "fast_check_next_run"
_CONFIG_FAULT_MARKER_NAME = "fast_check_config_fault_reported"


def _read_next_run(state_dir: Path | None) -> float:
    """The unix timestamp before which this hook should not run again, or
    0.0 meaning 'no restriction'."""
    if state_dir is None:
        return 0.0
    try:
        return float((state_dir / _NEXT_RUN_NAME).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def _write_next_run(state_dir: Path | None, when: float) -> None:
    if state_dir is None:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / _NEXT_RUN_NAME).write_text(str(when), encoding="utf-8")
    except OSError:
        pass


def _deferred(state_dir: Path | None, now: float) -> bool:
    """Whether the hook is still inside its stand-down window."""
    remaining = _read_next_run(state_dir) - now
    return 0 < remaining <= _TIMEOUT_BACKOFF_SECONDS


def _already_reported_fault(state_dir: Path | None) -> bool:
    return state_dir is not None and (state_dir / _CONFIG_FAULT_MARKER_NAME).exists()


def _mark_fault_reported(state_dir: Path | None) -> None:
    if state_dir is None:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / _CONFIG_FAULT_MARKER_NAME).write_text("", encoding="utf-8")
    except OSError:
        pass


def _configuration_fault_message(command: str, detail: str, *, once: bool) -> str:
    """Reported once per session where there is session state to remember with,
    and on every offending edit where there is not."""
    closing = (
        " Canon mentions this once per session and then stays quiet." if once else ""
    )
    return (
        f"Canon's fast check (`{command}`, from .canon/config.json's `check`) "
        f"cannot be run as configured: {detail} Fix the command in "
        ".canon/config.json -- this is a configuration problem, not something "
        "wrong with the change you just made." + closing
    )


def _report_configuration_fault(
    root: Path, state_dir: Path | None, command: str, detail: str
) -> None:
    """Report an unrunnable `check` once per session, where it can."""
    if _already_reported_fault(state_dir):
        _common.pass_post_tool()
        return
    _mark_fault_reported(state_dir)
    message = _configuration_fault_message(command, detail, once=state_dir is not None)
    _common.log_decision(root, "fast_check.py", "config_fault", reason=message)
    _common.context("PostToolUse", message, hook_name="canon-fast-check")


@_common.fail_open(fallback_fn=_common.pass_post_tool)
def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        _common.pass_post_tool()
        return

    if payload.get("error"):
        _common.pass_post_tool()
        return

    tool_name = _common.tool_name(payload)
    if tool_name not in _EDIT_TOOL_NAMES:
        _common.pass_post_tool()
        return

    if not _common.edited_paths(payload):
        _common.pass_post_tool()
        return

    if not _common.has_workspace(payload):
        _common.pass_post_tool()
        return

    root = _common.repo_root(payload)
    if not root.is_dir():
        _common.pass_post_tool()
        return

    config = _config.load_config(root)
    if not _config.canon_is_active(config):
        _common.pass_post_tool()
        return  # no verification signal: Canon is inert, not checking

    command = _config.fast_check_command(config)
    if command is None:
        _common.pass_post_tool()
        return  # this repository has not asked for layer one

    state_dir = _common.state_dir(payload)
    now = time.time()
    if _deferred(state_dir, now):
        _common.pass_post_tool()
        return

    problem = _config.verify_command_problem(command)
    if problem is not None:
        _report_configuration_fault(root, state_dir, command, problem)
        return

    _write_next_run(state_dir, now + _DEBOUNCE_SECONDS)
    result = _common.run_command(command, cwd=root, timeout=_FAST_CHECK_TIMEOUT_SECONDS)

    if result.passed:
        _common.pass_post_tool()
        return  # silence on clean pass

    if result.configuration_fault:
        _report_configuration_fault(root, state_dir, command, result.detail)
        return

    if result.timed_out:
        _write_next_run(state_dir, now + _TIMEOUT_BACKOFF_SECONDS)
        _common.log_decision(
            root, "fast_check.py", "timeout", reason=f"`{command}` timed out"
        )
        _common.pass_post_tool()
        return

    _common.log_decision(root, "fast_check.py", "failed", reason=result.detail)
    message = (
        f"Canon's fast check failed after this edit:\n{result.detail}\n"
        "This blocks nothing -- it is the cheap layer, run so a pull request "
        "never fails CI on formatting. If it came from this edit, fix it now; "
        "if it was already there, say so rather than widening this change to "
        "chase it."
    )
    _common.context("PostToolUse", message, hook_name="canon-fast-check")


if __name__ == "__main__":
    main()
