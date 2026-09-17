# SPDX-License-Identifier: BSD-3-Clause
"""Shared plumbing for every Canon hook, on every agent platform Canon
supports.

Standard library only, valid under Python 3.9. A hook runs on whatever
`python3` the host machine has, not on a resolved Bazel toolchain, so this
module imports nothing Canon ships and shells out to nothing -- unlike
CoDev's hooks, which resolved a `codev` CLI on every invocation and, by
CoDev's own decision log, found nothing to run 508 times out of 1,112. A
guardrail that depends on external resolution is a guardrail that silently
does nothing on exactly the machines it can't resolve on; this module has
no such dependency to fail.

This is the one canonical copy, at `src/canon_hooks/_common.py`. `just
sync-hooks` vendors it byte-for-byte into `plugins/claude/hooks/` and
`plugins/codex/hooks/`, because a hook runs via bare `python3` with only
its own directory on `sys.path` and cannot import a sibling package at
runtime. `just sync-check` fails if a vendored copy has drifted from this
one. A bug fixed here is fixed on every platform Canon ships for, in one
commit -- the whole reason this module lives here rather than being
maintained twice.

Every Canon gate fails open (see `fail_open`): a guardrail that errors must
never block work. And Canon writes no repository state -- the one file this
module writes, `.canon/hooks/decisions.jsonl`, is a gitignored local
diagnostic that is never read back to make a decision. The single permitted
exception is session-scoped counter state under `state_dir` -- used by
`stop.py`'s consecutive-refusal counter and `check_scope.py`'s
consecutive-departure counter, each documented on its own hook rather than
here.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple

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

    Prefers `cwd` from the payload -- every platform Canon ships for sets
    this to the project directory (confirmed directly for both Claude Code
    and Codex, not just documented). Falls back to `git rev-parse
    --show-toplevel` from the current process's own cwd, and finally to
    `Path.cwd()` itself -- this never raises, because a hook that can't
    find the repo root must still be able to fail open rather than crash.
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


def head_sha(root: Path) -> str | None:
    """The current HEAD's short SHA, or None if that can't be determined."""
    sha = _run_git(root, "rev-parse", "HEAD")
    return sha[:9] if sha else None


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout)


def allow() -> None:
    """PreToolUse: let the tool call proceed with no comment."""
    sys.exit(0)


def ask(reason: str) -> None:
    """PreToolUse: pause for confirmation, with a reason the agent can show."""
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
    """Stop: refuse to let the turn end, with a reason handed back to the
    agent."""
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


_OUTPUT_TAIL_CHARS = 4000


class CommandResult(NamedTuple):
    """What `run_command` learned, as four independent facts.

    `configuration_fault` and `timed_out` are deliberately separate
    booleans rather than one status enum, because they answer different
    questions and two different callers ask only one of them each:
    `stop.py` keeps a configuration fault out of its refusal budget,
    while `fast_check.py` stays silent on a timeout. A caller that
    string-matched `detail` to tell these apart would be one message
    rewrite away from breaking, which is why the runner reports them
    rather than describing them.
    """

    passed: bool
    detail: str
    configuration_fault: bool
    timed_out: bool


def run_command(root: Path, command: str, timeout: int) -> CommandResult:
    """Run `command` in `root` with **no shell**, and report the result.

    Returns a `CommandResult`.
    `configuration_fault` is True for the two ways this can go wrong that
    say nothing about whether the repository is healthy -- the command
    could not be parsed at all, or the named binary is not on `PATH`
    (`OSError`, typically `FileNotFoundError`) -- and False for a command
    that actually ran and either timed out or exited non-zero. A caller
    uses the flag to keep a misconfiguration from being reported, or
    counted against a budget, as though it were a red run.

    No shell, ever: see
    docs/decisions/0005-verify-command-never-runs-through-a-shell.md.
    A command that needs one is caught before it reaches here, by
    `_config.verify_command_problem`; the `ValueError` branch below stays
    as the defense in depth that decision describes, for a malformed
    command that slips past some other way -- an unbalanced quote, say,
    which is a parse failure rather than a metacharacter.

    Shared by `stop.py`, which runs the repository's verification command
    at a turn's end, and `fast_check.py`, which runs its fast check after
    an edit. They differ only in `timeout` and in what they do with the
    answer, so the running of it lives here rather than being written
    twice. `canon_mcp`'s own copy stays forked, because the hooks and the
    server share no dependency edge -- see `canon_mcp/_git.py`.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return CommandResult(False, f"Could not parse the command: {exc}", True, False)
    if not argv:
        return CommandResult(False, "The command is empty.", True, False)
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            False, f"`{command}` timed out after {timeout}s.", False, True
        )
    except OSError as exc:
        return CommandResult(False, f"Could not run `{command}`: {exc}", True, False)
    if completed.returncode == 0:
        return CommandResult(True, "", False, False)
    output = (completed.stdout or "") + (completed.stderr or "")
    return CommandResult(
        False,
        f"`{command}` exited {completed.returncode}:\n{output[-_OUTPUT_TAIL_CHARS:]}",
        False,
        False,
    )


def log_decision(
    root: Path,
    hook_name: str,
    decision: str,
    *,
    reason: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one local, gitignored diagnostic record.

    `extra` merges additional fields into the record (e.g. the HEAD SHA a
    review verdict was captured against) without those fields colliding
    with the base ones -- see `capture_review.py`'s use of `extra={"head":
    ...}`. Never raises: a broken log must never change a hook's own
    allow/ask/deny behavior, and this file is never read back by any hook
    to decide anything -- see the module docstring's no-stored-state rule.
    """
    try:
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hook": hook_name,
            "decision": decision,
            "reason": reason,
        }
        if extra:
            record.update(extra)
        path = root / _DECISIONS_LOG_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def last_decision(root: Path, hook_name: str) -> dict[str, Any] | None:
    """The most recently logged decision for `hook_name`, or None.

    Reads `_DECISIONS_LOG_RELATIVE` back for **display only** -- the one
    sanctioned exception to this module's "never read back to decide
    anything" rule (see the module docstring). A hook may surface this as
    informational context (e.g. a post-compaction recap of the last
    verification result); nothing may gate on it.
    """
    path = root / _DECISIONS_LOG_RELATIVE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(record, dict) and record.get("hook") == hook_name:
            return record
    return None


_SECTION_HEADING_PATTERN = re.compile(r"^## (.+?)\s*$", re.MULTILINE)


def plan_sections(body: str) -> dict[str, str]:
    """Split a plan's markdown body into `## `-heading sections.

    Keys are the heading text, lowercased and stripped -- matching every
    plan this repo's own hooks write. Used both to check a required
    section is present and non-empty (`save_plan.py`/`normalize_plan.py`)
    and to pull out a specific one for display (`session_start.py`'s
    recap).
    """
    matches = list(_SECTION_HEADING_PATTERN.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[name] = body[start:end].strip()
    return sections


_HEADER_DELIMITER = "---\n"
_HEADER_END_MARKER = "\n---\n"


def _unescape_scalar(value: str) -> str:
    """Reverse `plan_header.py`'s `_yaml_scalar` escaping: a backslash
    always means "take the next character literally"."""
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            result.append(value[index + 1])
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _split_document(text: str) -> tuple[str, str] | None:
    """Split a saved plan file into (header text, body text), or None if
    it doesn't start with a `---` header block."""
    if not text.startswith(_HEADER_DELIMITER):
        return None
    rest = text[len(_HEADER_DELIMITER) :]
    end_index = rest.find(_HEADER_END_MARKER)
    if end_index == -1:
        return None
    header_text = rest[:end_index]
    body_text = rest[end_index + len(_HEADER_END_MARKER) :].lstrip("\n")
    return header_text, body_text


def _parse_header_lines(header_text: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in header_text.splitlines():
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        if (
            len(raw_value) >= 2
            and raw_value.startswith('"')
            and raw_value.endswith('"')
        ):
            header[key] = _unescape_scalar(raw_value[1:-1])
        else:
            header[key] = raw_value
    return header


def plan_header_and_body(text: str) -> tuple[dict[str, str], str]:
    """Parse a saved plan file into (header dict, body text).

    Handles exactly the shape `plan_header.py`'s own `_format_header`
    writes: `key: "quoted value"` or a bare `key:` -- not general YAML.
    `{}` and the whole `text` as body if there's no `---` header block
    (e.g. a hand-written file no hook has touched yet) -- degrades
    gracefully rather than raising, same as every other reader in this
    module.
    """
    split = _split_document(text)
    if split is None:
        return {}, text
    header_text, body_text = split
    return _parse_header_lines(header_text), body_text


def parse_header(text: str) -> dict[str, str]:
    """Parse a saved plan's `---`-delimited header into `{key: value}`.
    See `plan_header_and_body` for the format and fallback behavior."""
    return plan_header_and_body(text)[0]


def edited_paths(payload: dict[str, Any] | None) -> list[str]:
    """Every file path an edit call's `tool_input` names, extracted
    defensively.

    Claude Code's edit tools report a single `tool_input.file_path`.
    Codex also offers `Edit`/`Write`, plus `apply_patch`, whose own
    `tool_input` shape was not possible to confirm empirically (see
    docs/codex-hook-surface.md) -- so this tries, in order, `file_path`,
    `path`, and a `changes` list of `{"path": ...}` entries (the shape
    Codex's own `codex exec --json` event stream uses for a file change).
    An empty list means "couldn't tell", which every caller must treat as
    a no-op rather than an error -- the same fail-open posture as
    everywhere else in this module.
    """
    if payload is None:
        return []
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    single = tool_input.get("file_path") or tool_input.get("path")
    if isinstance(single, str) and single:
        return [single]
    changes = tool_input.get("changes")
    if isinstance(changes, list):
        paths = [
            entry["path"]
            for entry in changes
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        ]
        if paths:
            return paths
    return []


_STATE_SUBDIR_DEFAULT = "canon"
_STATE_TEMP_ROOT_NAME = "canon-hooks"


def state_dir(
    payload: dict[str, Any] | None, subdir: str = _STATE_SUBDIR_DEFAULT
) -> Path | None:
    """The session-scoped directory a hook may keep state under, if any.

    Never under the repository, and never read back to decide anything
    beyond the current session -- this is the one kind of state Canon
    hooks are allowed to keep (see this module's docstring).

    Two sources, tried in order:

    1. `scratchpad_dir` in the payload -- what Claude Code sets, a
       directory it already manages the lifecycle of.
    2. `session_id` in the payload -- present on every Codex hook event
       (confirmed directly; Codex's payload carries no scratchpad
       directory of its own), used to derive one:
       `<tempdir>/canon-hooks/<session_id>/<subdir>`. This directory is
       never cleaned up by Canon itself, the same way Claude Code's own
       scratchpad is not this module's responsibility either -- it is
       the host platform's session state, just not handed to hooks
       ready-made on Codex the way it is on Claude Code.

    None when neither is present -- callers must treat that as "remember
    nothing," not as an error.
    """
    if payload is None:
        return None
    raw = payload.get("scratchpad_dir")
    if isinstance(raw, str) and raw:
        return Path(raw) / subdir
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id:
        return Path(tempfile.gettempdir()) / _STATE_TEMP_ROOT_NAME / session_id / subdir
    return None
