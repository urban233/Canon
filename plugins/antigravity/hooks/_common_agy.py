# SPDX-License-Identifier: BSD-3-Clause
"""Shared plumbing for Google Antigravity Canon hooks.

Standard library only, valid under Python 3.9+. Handles Antigravity's
protojson camelCase stdin/stdout contracts, scratchpad state resolution
under `artifactDirectoryPath / conversationId / canon`, and wraps hook
entry points in a fail-open decorator so errors never block agent progress.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_DECISIONS_LOG_RELATIVE = ".canon/hooks/decisions.jsonl"
_GIT_TIMEOUT_SECONDS = 10
_STATE_SUBDIR_DEFAULT = "canon"
_OUTPUT_TAIL_CHARS = 4000


# =============================================================================
# Payload Handling & Ingestion (Stdin)
# =============================================================================


def read_payload() -> dict[str, Any] | None:
    """Parse the hook's JSON input from stdin.

    Returns None on anything malformed -- empty stdin, invalid JSON, or a
    top-level value that isn't an object -- rather than raising. Callers
    must treat None as "fail open", never as an error to surface.
    """
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError, OSError, UnicodeDecodeError):
        return None


def repo_root(payload: dict[str, Any] | None) -> Path:
    """The repository root the hook should act on.

    Prefers `workspacePaths[0]` from the Antigravity payload.
    Falls back to `cwd` from payload (legacy/Claude compatibility),
    then `git rev-parse --show-toplevel`, and finally `Path.cwd()`.
    Never raises.
    """
    if payload:
        workspace_paths = payload.get("workspacePaths")
        if (
            isinstance(workspace_paths, list)
            and workspace_paths
            and isinstance(workspace_paths[0], str)
            and workspace_paths[0]
        ):
            return Path(workspace_paths[0])
        raw_cwd = payload.get("cwd")
        if isinstance(raw_cwd, str) and raw_cwd:
            return Path(raw_cwd)
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


def has_workspace(payload: dict[str, Any] | None) -> bool:
    """Whether the payload contains a valid, non-empty workspacePaths[0]."""
    if not payload or not isinstance(payload, dict):
        return False
    workspace_paths = payload.get("workspacePaths")
    return bool(
        isinstance(workspace_paths, list)
        and workspace_paths
        and isinstance(workspace_paths[0], str)
        and workspace_paths[0].strip()
    )


def state_dir(
    payload: dict[str, Any] | None, subdir: str = _STATE_SUBDIR_DEFAULT
) -> Path | None:
    """The session-scoped directory a hook may keep state under, if any.

    Strictly resolves to:
        Path(payload["artifactDirectoryPath"]) / payload["conversationId"] / subdir
    Returns None if payload is None or if artifactDirectoryPath or conversationId
    is missing or empty. Callers must treat None as "remember nothing", not as an error.
    """
    if not payload:
        return None
    artifact_dir = payload.get("artifactDirectoryPath")
    conversation_id = payload.get("conversationId")
    if (
        isinstance(artifact_dir, str)
        and artifact_dir
        and isinstance(conversation_id, str)
        and conversation_id
    ):
        return Path(artifact_dir) / conversation_id / subdir
    # Fallback for Claude compatibility if scratchpad_dir is present
    scratchpad = payload.get("scratchpad_dir")
    if isinstance(scratchpad, str) and scratchpad:
        return Path(scratchpad) / subdir
    return None


# =============================================================================
# Tool Extraction Accessors
# =============================================================================


def tool_call(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract toolCall object from payload, or None."""
    if not payload or not isinstance(payload, dict):
        return None
    tc = payload.get("toolCall")
    return tc if isinstance(tc, dict) else None


def tool_name(payload: dict[str, Any] | None) -> str | None:
    """Extract tool name from toolCall (or fallback tool_name)."""
    tc = tool_call(payload)
    if tc:
        name = tc.get("name")
        if isinstance(name, str):
            return name
    if payload and isinstance(payload, dict):
        name = payload.get("tool_name")
        if isinstance(name, str):
            return name
    return None


def tool_args(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Extract args dict from toolCall (or fallback tool_input)."""
    tc = tool_call(payload)
    if tc:
        args = tc.get("args")
        if isinstance(args, dict):
            return args
    if payload and isinstance(payload, dict):
        args = payload.get("tool_input")
        if isinstance(args, dict):
            return args
    return {}


def tool_command(payload: dict[str, Any] | None) -> str | None:
    """Extract command line string from tool args.
    Checks `CommandLine`, `command`, `cmd`.
    """
    args = tool_args(payload)
    for key in ("CommandLine", "command", "cmd"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def tool_target_file(payload: dict[str, Any] | None) -> str | None:
    """Extract target file path string from tool args.
    Checks `TargetFile`, `target_file`, `file_path`, `filePath`.
    """
    args = tool_args(payload)
    for key in ("TargetFile", "target_file", "file_path", "filePath"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def tool_code_content(payload: dict[str, Any] | None) -> str | None:
    """Extract code content string from tool args.
    Checks `CodeContent`, `code_content`, `content`.
    """
    args = tool_args(payload)
    for key in ("CodeContent", "code_content", "content"):
        val = args.get(key)
        if isinstance(val, str):
            return val
    return None


def edited_paths(payload: dict[str, Any] | None) -> list[str]:
    """Every file path an edit tool names in payload, extracted defensively."""
    if payload is None or not isinstance(payload, dict):
        return []
    paths: list[str] = []

    def _add(path_val: Any) -> None:
        if (
            isinstance(path_val, str)
            and path_val.strip()
            and path_val.strip() not in paths
        ):
            paths.append(path_val.strip())

    _add(tool_target_file(payload))

    args = tool_args(payload)
    for key in (
        "TargetFile",
        "targetFile",
        "target_file",
        "filePath",
        "FilePath",
        "file_path",
        "path",
        "Path",
    ):
        _add(args.get(key))

    changes = args.get("changes")
    if isinstance(changes, list):
        for entry in changes:
            if isinstance(entry, dict):
                for key in (
                    "path",
                    "filePath",
                    "file_path",
                    "targetFile",
                    "target_file",
                ):
                    _add(entry.get(key))

    return paths


# =============================================================================
# Output Payload Emitters (Stdout)
# =============================================================================


def _emit(payload: dict[str, Any]) -> dict[str, Any]:
    """Serialize payload to stdout and flush."""
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return payload


def allow(
    reason: str | None = None, overwrite: dict[str, Any] | None = None
) -> dict[str, Any]:
    """PreToolUse: let the tool call proceed.

    Emits {"decision": "allow", ...} and exits 0.
    """
    payload: dict[str, Any] = {"decision": "allow"}
    if reason is not None:
        payload["reason"] = reason
    if overwrite is not None:
        payload["overwrite"] = overwrite
    _emit(payload)
    sys.exit(0)


def deny(reason: str) -> dict[str, Any]:
    """PreToolUse: refuse the tool call outright with an explanation.

    Emits {"decision": "deny", "reason": reason} and exits 0.
    """
    payload: dict[str, Any] = {"decision": "deny", "reason": reason}
    _emit(payload)
    sys.exit(0)


def ask(reason: str) -> dict[str, Any]:
    """PreToolUse: pause for interactive confirmation.

    Emits {"decision": "ask", "reason": reason} and exits 0.
    """
    payload: dict[str, Any] = {"decision": "ask", "reason": reason}
    _emit(payload)
    sys.exit(0)


def continue_turn(reason: str) -> dict[str, Any]:
    """Stop: block turn completion and force agent continuation.

    Emits {"decision": "continue", "reason": reason} and exits 0.
    """
    payload: dict[str, Any] = {"decision": "continue", "reason": reason}
    _emit(payload)
    sys.exit(0)


def pass_stop() -> dict[str, Any]:
    """Stop: allow turn completion (tests pass or gave up).

    Emits {} and exits 0.
    """
    payload: dict[str, Any] = {}
    _emit(payload)
    sys.exit(0)


def pass_post_tool() -> dict[str, Any]:
    """PostToolUse: let tool execution record complete.

    Emits {} and exits 0.
    """
    return pass_stop()


def inject_context(message: str) -> dict[str, Any]:
    """PreInvocation: inject ephemeral context before model turn.

    Emits {"injectSteps": [{"ephemeralMessage": message}]} (or [] if empty) and exits 0.
    """
    steps = [{"ephemeralMessage": message}] if message else []
    payload: dict[str, Any] = {"injectSteps": steps}
    _emit(payload)
    sys.exit(0)


def context(
    event_type: str = "PostToolUse",
    message: str = "",
    hook_name: str | None = None,
) -> dict[str, Any]:
    """PostToolUse: emit non-blocking additionalContext and exit 0.

    Emits {"additionalContext": message, ...} and exits 0.
    """
    known_events = {"PostToolUse", "PreToolUse", "PreInvocation", "Stop"}
    if event_type not in known_events and not message:
        message = event_type
        event_type = "PostToolUse"
    payload: dict[str, Any] = {
        "additionalContext": message,
        "hookSpecificOutput": {
            "hookEventName": event_type,
            "additionalContext": message,
        },
    }
    if hook_name:
        payload["hookSpecificOutput"]["hookName"] = hook_name
    _emit(payload)
    sys.exit(0)


# =============================================================================
# Command Execution Utilities
# =============================================================================


class CommandResult:
    """The result of running a command without a shell."""

    def __init__(
        self,
        exit_code_or_passed: int | bool = 0,
        stdout_or_detail: str = "",
        stderr_or_config_fault: str | bool = "",
        timed_out: bool = False,
        configuration_fault: bool = False,
        *,
        passed: bool | None = None,
        detail: str | None = None,
        exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ):
        if isinstance(exit_code_or_passed, bool):
            self._passed_override = exit_code_or_passed
            self._detail_override = str(stdout_or_detail)
            self.configuration_fault = bool(stderr_or_config_fault)
            self.timed_out = bool(timed_out)
            if self._passed_override:
                self.exit_code = 0
            elif self.timed_out:
                self.exit_code = 124
            elif self.configuration_fault:
                self.exit_code = 127
            else:
                self.exit_code = 1
            self.stdout = "" if self._passed_override else self._detail_override
            self.stderr = ""
        else:
            self.exit_code = (
                int(exit_code_or_passed) if exit_code is None else int(exit_code)
            )
            self.stdout = str(stdout_or_detail) if stdout is None else str(stdout)
            self.stderr = str(stderr_or_config_fault) if stderr is None else str(stderr)
            self.timed_out = bool(timed_out)
            self.configuration_fault = bool(configuration_fault)
            self._passed_override = passed
            self._detail_override = detail

    @property
    def passed(self) -> bool:
        if self._passed_override is not None:
            return self._passed_override
        return (
            self.exit_code == 0 and not self.timed_out and not self.configuration_fault
        )

    @property
    def failed(self) -> bool:
        return not self.passed

    @property
    def detail(self) -> str:
        if self._detail_override is not None:
            return self._detail_override
        output = (self.stdout or "") + (self.stderr or "")
        if self.configuration_fault:
            return self.stderr or self.stdout or "configuration fault"
        if self.timed_out:
            return "timed out"
        if self.exit_code != 0:
            return (
                f"exited {self.exit_code}:\n{output[-_OUTPUT_TAIL_CHARS:]}"
                if output
                else f"exited {self.exit_code}"
            )
        return output

    def __iter__(self):
        yield self.exit_code
        yield self.stdout
        yield self.stderr
        yield self.timed_out
        yield self.configuration_fault

    def __repr__(self) -> str:
        return (
            f"CommandResult(exit_code={self.exit_code}, stdout={self.stdout!r}, "
            f"stderr={self.stderr!r}, timed_out={self.timed_out}, "
            f"configuration_fault={self.configuration_fault})"
        )


def run_command(
    command_or_root: str | Path,
    cwd_or_command: Path | str | None = None,
    timeout: int | None = None,
    *,
    cwd: Path | None = None,
) -> CommandResult:
    """Run a command directly with no shell.

    Supports:
        run_command(command, cwd=root, timeout=60)
        run_command(root, command, timeout=60)
        run_command(command, cwd, timeout)
    """
    if isinstance(command_or_root, Path) or (
        isinstance(cwd_or_command, str) and not isinstance(command_or_root, str)
    ):
        root = Path(command_or_root)
        command = str(cwd_or_command)
    elif isinstance(cwd_or_command, (Path, str)) and timeout is not None:
        command = str(command_or_root)
        root = Path(cwd_or_command)
    else:
        command = str(command_or_root)
        root = (
            cwd
            if cwd is not None
            else (
                Path(cwd_or_command) if isinstance(cwd_or_command, Path) else Path.cwd()
            )
        )

    effective_timeout = timeout if timeout is not None else 300

    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return CommandResult(
            exit_code=1,
            stdout="",
            stderr=f"Could not parse the command: {exc}",
            configuration_fault=True,
            detail=f"could not parse this command: {exc}",
        )
    if not argv:
        return CommandResult(
            exit_code=1,
            stdout="",
            stderr="The command is empty.",
            configuration_fault=True,
            detail="this command is empty",
        )
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            exit_code=124,
            stdout="",
            stderr=f"`{command}` timed out after {effective_timeout}s.",
            timed_out=True,
            detail=f"`{command}` timed out after {effective_timeout}s.",
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return CommandResult(
            exit_code=127,
            stdout="",
            stderr=f"Could not run `{command}`: {exc}",
            configuration_fault=True,
            detail=f"Could not run `{command}`: {exc}",
        )

    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return CommandResult(
            exit_code=0,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            passed=True,
            detail="",
        )
    return CommandResult(
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        passed=False,
        detail=(
            f"`{command}` exited {completed.returncode}:\n"
            f"{output[-_OUTPUT_TAIL_CHARS:]}"
        ),
    )


# =============================================================================
# Fail-Open Harness
# =============================================================================


def _make_fail_open_wrapper(
    main_fn: Callable[..., Any], fallback: Callable[..., Any]
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return main_fn(*args, **kwargs)
        except SystemExit:
            raise
        except (Exception, KeyboardInterrupt) as exc:
            try:
                sys.stderr.write(f"Canon hook error (failing open): {exc}\n")
                sys.stderr.flush()
            except Exception:
                pass
            try:
                res = fallback()
                if isinstance(res, dict):
                    _emit(res)
            except SystemExit:
                raise
            except Exception:
                pass
            sys.exit(0)

    return wrapped


def fail_open(
    func_or_fallback: Callable[..., Any] | None = None,
    *,
    fallback_fn: Callable[..., Any] | None = None,
) -> Any:
    """Decorator/wrapper ensuring any unhandled exception exits 0 with neutral JSON.

    Supported calling conventions:
    1. @fail_open
       def main(): ...
    2. @fail_open(fallback_fn=pass_stop)
       def main(): ...
    3. fail_open(main)()
    4. fail_open(fallback_fn=pass_stop)(main)()
    5. fail_open(pass_stop)(main)()
    """
    default_fallback = allow

    # Case A: fail_open(fallback_fn=pass_stop) -> returns decorator
    if func_or_fallback is None:
        effective_fallback = (
            fallback_fn if fallback_fn is not None else default_fallback
        )
        return lambda target: _make_fail_open_wrapper(target, effective_fallback)

    # Case B: fail_open(main, fallback_fn=pass_stop)
    if fallback_fn is not None:
        return _make_fail_open_wrapper(func_or_fallback, fallback_fn)

    # Case C: func_or_fallback provided positionally without fallback_fn
    class _DualFailOpen:
        def __init__(self, target_or_fallback: Callable[..., Any]):
            self._target_or_fallback = target_or_fallback
            self._wrapper = _make_fail_open_wrapper(
                target_or_fallback, default_fallback
            )

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            if len(args) == 1 and callable(args[0]) and not kwargs:
                return _make_fail_open_wrapper(args[0], self._target_or_fallback)
            return self._wrapper(*args, **kwargs)

    return _DualFailOpen(func_or_fallback)


# =============================================================================
# Shared Git & Plan Parsing Utilities
# =============================================================================


def _run_git(root: Path, *args: str) -> str | None:
    """Run a read-only git command in `root`."""
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
    branch = _run_git(root, "branch", "--show-current")
    if branch:
        return branch
    return _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")


def default_branch(root: Path) -> str:
    """The repository's default branch, best-effort (origin/HEAD or 'main')."""
    ref = _run_git(root, "rev-parse", "--abbrev-ref", "origin/HEAD")
    if ref and ref.startswith("origin/"):
        return ref[len("origin/") :]
    return "main"


def merge_base(root: Path, default_branch_name: str) -> str | None:
    """The short SHA where current branch diverged from default branch."""
    sha = _run_git(root, "merge-base", "HEAD", default_branch_name)
    return sha[:9] if sha else None


def head_sha(root: Path) -> str | None:
    """The current HEAD's short SHA, or None."""
    sha = _run_git(root, "rev-parse", "HEAD")
    return sha[:9] if sha else None


def log_decision(
    root: Path,
    hook_name: str,
    decision: str,
    *,
    reason: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one local, gitignored diagnostic record."""
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
    """The most recently logged decision for `hook_name`, or None."""
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
    """Split a plan's markdown body into `## `-heading sections."""
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
    """Parse a saved plan file into (header dict, body text)."""
    split = _split_document(text)
    if split is None:
        return {}, text
    header_text, body_text = split
    return _parse_header_lines(header_text), body_text


def parse_header(text: str) -> dict[str, str]:
    """Parse a saved plan's `---`-delimited header into `{key: value}`."""
    return plan_header_and_body(text)[0]
