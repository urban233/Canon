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
and a build tool serialises per output base. A `check` firing while
`verify`, or a developer's own `just ci`, holds that lock would spend its
whole budget waiting and then report a timeout. Reported as a failure,
that is indistinguishable from a real regression the edit introduced, and
an advisory layer that cries wolf is one a developer learns to ignore. So
a timeout produces no output at all: layer one has no authority, which
means an unknown answer costs nothing. `_common.run_command` already
separates a timeout from a non-zero exit, and this hook is the reason
that distinction earns its place twice.

Pointing `check` at its own output base would dodge the contention
instead, and an earlier draft of this repository's own config did. It was
withdrawn: a fixed path under a shared `/tmp` is a permissions failure
waiting for the second user of a machine, and that arrives here as a
non-zero exit rather than an `OSError` -- so Canon would tell an agent its
edit broke something when the truth is that another account owns a
directory. Waiting on a lock and saying nothing is the better failure, and
it is the one this hook is already built for.

**A timeout also stands the hook down for longer.** The window is written
before the command runs, so without that a `check` that reliably exceeds
its budget would spawn a 60-second subprocess every debounce window, for
ever, to emit nothing each time.

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

# `None` is included to match check_scope.py, which is bound to the same
# event: a payload that carries no `tool_name` at all is a shape
# docs/codex-hook-surface.md records as unconfirmed, and two hooks on one
# event disagreeing about whether to act on it would be worse than either
# answer.
_EDIT_TOOL_NAMES = (None, "Edit", "Write", "apply_patch")

_FAST_CHECK_TIMEOUT_SECONDS = 60
# Neither is a config key, on purpose -- see the module docstring.
_DEBOUNCE_SECONDS = 30
# A check that timed out is one that is structurally too slow for this
# layer, or one waiting on a lock it will keep waiting on. Standing down
# for longer than the ordinary window keeps a repository whose `check`
# reliably overruns from paying a 60-second stall every 30 seconds
# forever, for a report it never even emits.
_TIMEOUT_BACKOFF_SECONDS = 600

_NEXT_RUN_NAME = "fast_check_next_run"
_CONFIG_FAULT_MARKER_NAME = "fast_check_config_fault_reported"


def _read_next_run(state_dir: Path | None) -> float:
    """The unix timestamp before which this hook should not run again, or
    0.0 meaning "no restriction".

    0.0 for a missing, unreadable or malformed marker, and for no
    `state_dir` at all -- every one of which means "run it", which is the
    degraded behaviour this hook wants: without session state it stops
    debouncing rather than stopping working.
    """
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
    """Whether the hook is still inside its stand-down window.

    The upper bound matters as much as the lower one. A stamp further
    ahead than any window this module writes cannot have come from this
    module -- a clock corrected backwards by NTP, a resumed laptop, a
    container with skewed time -- and treating it as a deferral would
    silently disable the check for the length of the skew. An implausible
    stamp is therefore treated as no stamp, which fails toward running.
    """
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
    """Reported once per session where there is session state to remember
    with, and on every offending edit where there is not.

    `once` is not decoration: without a `state_dir` the marker cannot be
    written, so the claim "Canon mentions this once" would be false on
    exactly the platforms that cannot keep it. Saying less is better than
    asserting a property the code does not hold -- the same care
    `stop.py`'s equivalent takes.

    Deliberately the same shape as that equivalent otherwise: a command
    that cannot be run is a fact about `.canon/config.json`, not about the
    code, and telling the agent to fix the code is how a misconfiguration
    gets "repaired" into a real change.
    """
    closing = (
        " Canon mentions this once per session and then stays quiet." if once else ""
    )
    return (
        f"Canon's fast check (`{command}`, from .canon/config.json's `check`) "
        f"cannot be run as configured: {detail} Fix the command in "
        ".canon/config.json -- this is a configuration problem, not something "
        "wrong with the change you just made." + closing
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
    now = time.time()
    # Ahead of every other branch, including the configuration-fault
    # report: an edit-heavy turn should cost this hook nothing at all,
    # whatever it would have had to say.
    if _deferred(state_dir, now):
        return

    problem = _config.verify_command_problem(command)
    if problem is not None:
        _report_configuration_fault(root, state_dir, command, problem)
        return

    _write_next_run(state_dir, now + _DEBOUNCE_SECONDS)
    result = _common.run_command(root, command, _FAST_CHECK_TIMEOUT_SECONDS)
    if result.passed:
        return  # silence is the whole point of a layer with no authority

    if result.configuration_fault:
        _report_configuration_fault(root, state_dir, command, result.detail)
        return

    if result.timed_out:
        # See the module docstring: a timeout is very likely this hook
        # waiting on a build-tool lock another Canon gate is holding, and
        # reporting that as a failure is indistinguishable from a real
        # regression. An advisory layer says nothing rather than something
        # it cannot stand behind -- and stands down for longer, so a
        # `check` that is structurally too slow costs one stall rather
        # than one every debounce window forever.
        _write_next_run(state_dir, now + _TIMEOUT_BACKOFF_SECONDS)
        _common.log_decision(
            root, "fast_check.py", "timeout", reason=f"`{command}` timed out"
        )
        return

    _common.log_decision(root, "fast_check.py", "failed", reason=result.detail)
    _common.context(
        "PostToolUse",
        f"Canon's fast check failed after this edit:\n{result.detail}\n"
        "If it came from this edit, fix it now; "
        "if it was already there, say so rather than widening this change to "
        "chase it.",
    )


def _report_configuration_fault(
    root: Path, state_dir: Path | None, command: str, detail: str
) -> None:
    """Report an unrunnable `check` once per session, where it can."""
    if _already_reported_fault(state_dir):
        return
    _mark_fault_reported(state_dir)
    message = _configuration_fault_message(command, detail, once=state_dir is not None)
    _common.log_decision(root, "fast_check.py", "config_fault", reason=message)
    _common.context("PostToolUse", message)


if __name__ == "__main__":
    _common.fail_open(main)()
