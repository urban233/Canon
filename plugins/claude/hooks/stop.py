# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `Stop` hook — the verification gate.

Invariant III ("nothing ships on the agent's own word") is a precondition:
if this repository has no configured verification command, Canon stays
inert rather than operating unverified (see docs/plan.md §07, "No signal,
no Canon"). So this hook does one of three things on every `Stop` event:

- No `verify` command in `.canon/config.json` yet: block once per
  session to surface the first-run question -- proposing whatever
  `_config.suggest_verify_command` inferred, or asking outright when
  nothing was inferred -- then allow silently on every later `Stop` in
  the same session. A `Stop` hook has no "ask" permission decision and no
  TTY-based degradation the way `PreToolUse` does; `block` is the only
  mechanism that reliably puts text in front of the agent, which is then
  expected to relay the question to the developer and, once answered,
  write `.canon/config.json` itself -- a plain file edit, not a new tool.
- A `verify` command is configured, but cannot actually be run as
  written -- `_config.verify_command_problem` says why, most often
  because it is compound (`ruff check . && pytest`) and Canon runs it
  with no shell. This is a configuration fault, not a red result: it
  says nothing about whether the repository's tests pass, so it must
  never be reported as one, never counted against the
  consecutive-refusal budget below, and never left for the developer to
  discover only by noticing the same error every single turn. It gets
  the identical treatment as the first-run question -- block once per
  session with a reason that names the actual file to fix
  (`_config.verify_command_source`: `.canon/config.json`, or the plan
  header's file when that is what resolved to this command), then
  allow -- because an unrunnable command *is* "no signal" under §07,
  just discovered a turn later than a missing one.
- A `verify` command is configured and runs: block on a red result,
  attaching the failure so the claim "tests pass" is something the
  harness checked rather than something the agent asserted. Here too a
  command that could not even be executed -- its binary is not on
  `PATH` -- is a configuration fault handled the way above, not a red
  result; only a command that ran and exited non-zero (or timed out)
  counts against the refusal budget.

The one state this hook is allowed to remember, per `_common.py`'s module
docstring and `AGENTS.md`: two same-session markers (so the first-run
question and the configuration-fault report are each surfaced once, not
on every `Stop`) and a consecutive-refusal counter (so a run of genuinely
red results doesn't block forever). All three live under
`_common.state_dir` -- the `scratchpad_dir` Claude Code includes in the
`Stop` payload, or, on a platform that includes no such directory (Codex
does not -- confirmed directly, see docs/codex-hook-surface.md), one
`state_dir` derives itself from the payload's `session_id`. Either way,
never under the repository.

When `state_dir` returns None -- neither source was available -- all
three degrade to their empty state, and an empty state is not a safe one
here: an always-zero counter never reaches its cap, so a persistently red
repository would block every turn end for good, and an always-absent
marker asks the same question on every `Stop` rather than once. So
`stop_hook_active` -- the harness's own signal that this turn is already
continuing because a `Stop` hook blocked it -- stands in for all three,
but *only* in that fully-degraded case. It cannot count, so it is a
strictly weaker guarantee than three attempts: one block, then through.
That is the right trade for a degraded payload and the wrong one for a
healthy session, which is why it is a fallback rather than the mechanism.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

import _common
import _config

_MAX_CONSECUTIVE_REFUSALS = 3
_VERIFY_TIMEOUT_SECONDS = 300
_OUTPUT_TAIL_CHARS = 4000

_PROMPTED_MARKER_NAME = "verify_prompted"
_CONFIG_FAULT_MARKER_NAME = "verify_config_fault_prompted"
_REFUSAL_COUNTER_NAME = "consecutive_refusals"


def _stop_hook_active(payload: dict[str, Any] | None) -> bool:
    """Whether the harness says this turn is already continuing because a
    `Stop` hook blocked it. Absent or non-boolean reads as False."""
    return bool(payload.get("stop_hook_active")) if payload else False


def _has_been_prompted(
    state_dir: Path | None,
    stop_hook_active: bool,
    marker_name: str = _PROMPTED_MARKER_NAME,
) -> bool:
    """Whether the once-per-session marker named by `marker_name` is
    already set. Two independent markers use this: the first-run
    question (`_PROMPTED_MARKER_NAME`) and the configuration-fault
    report (`_CONFIG_FAULT_MARKER_NAME`) -- see the module docstring.
    They are deliberately separate files, not one shared marker, so a
    session that has already been told "no command configured" still
    gets told, once, "the command you configured cannot run" if the
    developer's answer to the first turns out to be unrunnable."""
    if state_dir is None:
        return stop_hook_active
    return (state_dir / marker_name).exists()


def _mark_prompted(
    state_dir: Path | None, marker_name: str = _PROMPTED_MARKER_NAME
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
    there is no counter, so the harness's own loop guard is all that can
    end the run -- see the module docstring for why a one-shot backstop
    is accepted there and only there.
    """
    if state_dir is None:
        return stop_hook_active
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
        "yet, and stays inert until it does. " + ask + " Run the candidate "
        "yourself and show the developer what actually happened -- pass, "
        "fail, or error -- before either of you settles on it: a command "
        "neither of you has watched run is still a guess, and docs/plan.md "
        "§07 is explicit that a wrong-but-plausible guess is worse than no "
        "answer at all. Confirm it with the developer, then save it by "
        'writing {"verify": "<command>"} to .canon/config.json. One thing '
        "the answer cannot be: compound. Canon runs this command directly, "
        "with no shell, so `a && b`, `a || b`, a pipe, a `;`-separated "
        "sequence, or anything else only a shell would know how to run is "
        "refused rather than executed -- a partial failure inside a chain "
        "is exactly the ambiguous evidence this gate exists to eliminate, "
        "since there would be no way to tell which half went red. If the "
        "real answer is a sequence, the fix is a recipe or script that "
        "wraps it -- a Justfile recipe, an npm script, a shell script "
        "committed to the repo -- with that single command named here "
        "instead. Propose that wrapper to the developer -- do not write "
        "it yourself: editing this repository's build configuration is "
        "not Canon's job, the same line it holds on `nbstripout` and on "
        "branch protection."
    )


def _configuration_fault_reason(command: str, source: str, detail: str) -> str:
    """The message for a `verify` command that cannot be run as
    configured -- see the module docstring's second bullet. Named after
    `source` -- `.canon/config.json`, or the plan header's file when
    that is what actually resolved to this command, per
    `_config.verify_command_source` -- explicitly, because the whole
    point is that this must never be mistaken for a failing check: it
    says nothing about whether the repository's own tests pass, and
    naming the wrong file would send the developer to fix the wrong
    place."""
    return (
        f"The verify command in {source} (`{command}`) cannot be "
        f"run as configured: {detail} This is a configuration problem, not "
        f"a failing check -- relay it to the developer so they can fix "
        f"{source}. Canon will not block on this again this "
        "session, but it also cannot verify anything until it's fixed."
    )


def _run_verification(root: Path, command: str) -> tuple[bool, str, bool]:
    """Run `command` with no shell and report the result.

    Returns `(passed, detail, configuration_fault)`. `configuration_fault`
    is True for the two ways this can go wrong that have nothing to do
    with whether the repository's checks pass -- the command could not be
    parsed at all, or the named binary is not on `PATH` (`OSError`,
    typically `FileNotFoundError`) -- and False for a command that ran
    and either timed out or exited non-zero. `main` uses the flag to keep
    a configuration fault from being reported, or counted against the
    refusal budget, as though it were a red run; see
    `_configuration_fault_reason`.

    The compound-command case -- `ruff check . && pytest` becoming
    `['ruff', 'check', '.', '&&', 'pytest']` -- is caught earlier, by
    `_config.verify_command_problem`, before this function is ever
    called; the `ValueError` branch here remains as the same defense in
    depth `_config.shell_metacharacter`'s own docstring describes, for a
    malformed command that slips past that check some other way (for
    instance an unbalanced quote, which is a parse failure rather than a
    metacharacter).
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


def _handle_configuration_fault(
    root: Path,
    state_dir: Path | None,
    stop_hook_active: bool,
    command: str,
    source: str,
    detail: str,
) -> None:
    """Report `command` as unrunnable and end the hook -- either the
    once-per-session block, or silent allow if that block already
    happened this session. See the module docstring's second bullet:
    this is deliberately the same shape as the first-run question, not
    the refusal-counter path, because an unrunnable command is "no
    signal" under §07 just the same as a missing one."""
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
        _common.allow()
        return
    _mark_prompted(state_dir, marker_name=_CONFIG_FAULT_MARKER_NAME)
    _common.log_decision(root, "stop.py", "block", reason=reason)
    _common.block(reason)


def main() -> None:
    payload = _common.read_payload()
    root = _common.repo_root(payload)
    state_dir = _common.state_dir(payload)
    stop_hook_active = _stop_hook_active(payload)
    config = _config.load_config(root)

    if config is None or not _config.has_verification_signal(config):
        if _has_been_prompted(state_dir, stop_hook_active):
            _common.allow()
            return
        _mark_prompted(state_dir)
        _common.block(_first_run_reason(root))
        return

    branch = _common.current_branch(root)
    command = _config.resolve_verify_command(root, branch, config)
    if command is None:  # pragma: no cover - has_verification_signal implies one
        _common.allow()
        return

    # A command already on disk that cannot be run as configured (most
    # often: compound) is a configuration fault, caught before
    # `subprocess.run` ever sees it -- never reported as a failing check.
    # See docs/plan.md §07 and `_config.verify_command_problem`'s
    # docstring for why this must not read like a red suite.
    problem = _config.verify_command_problem(command)
    if problem is not None:
        source = _config.verify_command_source(root, branch, config)
        _handle_configuration_fault(
            root, state_dir, stop_hook_active, command, source, problem
        )
        return

    passed, detail, configuration_fault = _run_verification(root, command)
    if passed:
        _write_refusal_count(state_dir, 0)
        _common.log_decision(root, "stop.py", "allow", reason=f"`{command}` passed")
        _common.allow()
        return

    if configuration_fault:
        # Discovered only at execution time -- typically the named
        # binary is not on `PATH`. Same treatment as the pre-check
        # above and for the same reason: this is not evidence about the
        # repository's own tests, so it must not burn the refusal
        # budget or read like one did.
        source = _config.verify_command_source(root, branch, config)
        _handle_configuration_fault(
            root, state_dir, stop_hook_active, command, source, detail
        )
        return

    refusals = _read_refusal_count(state_dir) + 1
    if _should_give_up(state_dir, stop_hook_active, refusals):
        _write_refusal_count(state_dir, 0)
        _common.log_decision(
            root,
            "stop.py",
            "allow",
            reason=_give_up_reason(state_dir, refusals, detail),
        )
        _common.allow()
        return
    _write_refusal_count(state_dir, refusals)
    _common.log_decision(root, "stop.py", "block", reason=detail)
    _common.block(detail)


if __name__ == "__main__":
    _common.fail_open(main)()
