# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PostToolUse` hook for an edit -- the fast check.

docs/plan.md §11 sets out three quality layers at three latencies:
`PostToolUse` as each file is written (cosmetic, no authority), `Stop` at
the end of every turn (blocks the turn), and CI on the pull request
(blocks the merge). Layer one existed only on paper. §11 says it is there
"purely so neither of them ever fails for a reason as trivial as
whitespace" -- and in one session three pull requests failed CI on
`fmt_check` alone, every other check green on all of them. That is
precisely the failure the layer was specified to absorb.

**Why the command is named by the repository rather than inferred.**
Canon cannot run a formatter itself. Hooks are standard-library only and
run via bare `python3`, so they can resolve no tool; and in this very
repository `ruff` and `pyrefly` exist only inside Bazel's pip hub, with
no binary on `PATH` at all. Shelling out to whatever a hook can find is
the failure `_common.py`'s docstring was written against -- CoDev's hooks
resolved a CLI on every invocation and found nothing to run 508 times out
of 1,112. So `check` in `.canon/config.json` is the same shape as
`verify`: the repository states its own answer once, and Canon runs it.
See `_config.fast_check_command`.

**This hook never blocks, and never guesses.** `PostToolUse` fires after
the edit has already happened, so it could not deny anything even if it
wanted to; it emits `additionalContext` and nothing else, which is what
§11 means by "None -- cosmetic, never blocks".

**A timeout is silence, not a failure.** This is the one design point
worth stating at length, because getting it wrong would make the layer
worse than absent. A repository's `check` and its `verify` are both
likely to be the same build tool -- in this repository both are Bazel --
and Bazel serialises commands per output base. A `check` firing while
`verify`, or a developer's own `just ci`, holds that lock would spend its
whole budget waiting and then report a timeout. Reported as a failure,
that is indistinguishable from a real regression the edit introduced, and
an advisory layer that cries wolf is one a developer learns to ignore. So
a timeout produces no output at all: layer one has no authority, which
means an unknown answer costs nothing. `_common.run_command` already
separates a timeout from a non-zero exit, and this hook is the reason
that distinction earns its place twice.

**Debounced, deliberately.** An edit-heavy turn would otherwise pay the
command once per tool call. The interval is a module constant rather
than a config key: §09's claim is that Canon exposes exactly one
enumerated setting, and `.canon/config.json` is the surface on which
§02's "ceremony priced as if it were free" grows back. A knob nobody has
asked for does not earn a line in a file every contributor reads. The
timestamp lives under `_common.state_dir` -- session-scoped, never in the
repository -- which `_common.py` names as the single permitted exception
to Canon writing no state, and which `stop.py` and `check_scope.py`
already use for their own counters.

Inert without a verification signal (docs/plan.md §07, "No signal, no
Canon"): with no `verify` command in `.canon/config.json` this hook is a
silent no-op even when `check` is set, because a repository where Canon
may not act at all is not one where it may act a little. See
docs/decisions/0001-what-inert-means.md.
"""

from __future__ import annotations

import time
from pathlib import Path

import _common
import _config

_EDIT_TOOL_NAMES = ("Edit", "Write", "apply_patch")

_FAST_CHECK_TIMEOUT_SECONDS = 60
# Not a config key, on purpose -- see the module docstring.
_DEBOUNCE_SECONDS = 30

_LAST_RUN_NAME = "fast_check_last_run"
_CONFIG_FAULT_MARKER_NAME = "fast_check_config_fault_reported"


def _read_last_run(state_dir: Path | None) -> float:
    """When this hook last ran the check, as a unix timestamp, or 0.0.

    0.0 for a missing, unreadable or malformed marker, and for no
    `state_dir` at all -- every one of which means "run it", which is the
    degraded behaviour this hook wants: without session state it simply
    stops debouncing rather than stopping working.
    """
    if state_dir is None:
        return 0.0
    try:
        return float((state_dir / _LAST_RUN_NAME).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def _write_last_run(state_dir: Path | None, when: float) -> None:
    if state_dir is None:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / _LAST_RUN_NAME).write_text(str(when), encoding="utf-8")
    except OSError:
        pass


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


def _configuration_fault_message(command: str, detail: str) -> str:
    """Said once per session, then never again.

    Deliberately the same shape as `stop.py`'s equivalent: a command that
    cannot be run is a fact about `.canon/config.json`, not about the
    code, and telling the agent to fix the code is how a misconfiguration
    gets "repaired" into a real change.
    """
    return (
        f"Canon's fast check (`{command}`, from .canon/config.json's `check`) "
        f"cannot be run as configured: {detail} Fix the command in "
        ".canon/config.json -- this is a configuration problem, not something "
        "wrong with the change you just made. Canon mentions this once per "
        "session and then stays quiet."
    )


def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        return
    if payload.get("tool_name") not in _EDIT_TOOL_NAMES:
        return
    if not _common.edited_paths(payload):
        return  # couldn't tell what was touched -- do nothing, per _common

    root = _common.repo_root(payload)
    config = _config.load_config(root)
    if not _config.canon_is_active(config):
        return  # no verification signal: Canon is inert, not checking
    command = _config.fast_check_command(config)
    if command is None:
        return  # this repository has not asked for layer one

    state_dir = _common.state_dir(payload)

    problem = _config.verify_command_problem(command)
    if problem is not None:
        if _already_reported_fault(state_dir):
            return
        _mark_fault_reported(state_dir)
        message = _configuration_fault_message(command, problem)
        _common.log_decision(root, "fast_check.py", "config_fault", reason=message)
        _common.context("PostToolUse", message)
        return

    now = time.time()
    if now - _read_last_run(state_dir) < _DEBOUNCE_SECONDS:
        return
    _write_last_run(state_dir, now)

    result = _common.run_command(root, command, _FAST_CHECK_TIMEOUT_SECONDS)
    if result.passed:
        return  # silence is the whole point of a layer with no authority

    if result.configuration_fault:
        if _already_reported_fault(state_dir):
            return
        _mark_fault_reported(state_dir)
        message = _configuration_fault_message(command, result.detail)
        _common.log_decision(root, "fast_check.py", "config_fault", reason=message)
        _common.context("PostToolUse", message)
        return

    if result.timed_out:
        # See the module docstring: a timeout is very likely this hook
        # waiting on a build-tool lock another Canon gate is holding, and
        # reporting that as a failure is indistinguishable from a real
        # regression. An advisory layer says nothing rather than
        # something it cannot stand behind.
        _common.log_decision(
            root, "fast_check.py", "timeout", reason=f"`{command}` timed out"
        )
        return

    _common.log_decision(root, "fast_check.py", "failed", reason=result.detail)
    _common.context(
        "PostToolUse",
        f"Canon's fast check failed after this edit:\n{result.detail}\n"
        "This blocks nothing -- it is the cheap layer, run so a pull request "
        "never fails CI on formatting. Fix it now if it came from this edit.",
    )


if __name__ == "__main__":
    _common.fail_open(main)()
