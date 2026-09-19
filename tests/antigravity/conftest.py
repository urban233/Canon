# SPDX-License-Identifier: BSD-3-Clause
"""Test configuration, isolated module loader, and fixtures for Antigravity hooks."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGY_PLUGIN_DIR = REPO_ROOT / "plugins" / "antigravity"
AGY_HOOKS_DIR = AGY_PLUGIN_DIR / "hooks"
AGY_SKILLS_DIR = AGY_PLUGIN_DIR / "skills"

_AGY_MODULE_CACHE: dict[str, Any] = {}


def load_agy_module(name: str) -> Any:
    """Load an Antigravity hook module with complete bidirectional isolation.

    Ensures that Antigravity hooks (like `stop`, `_config`, `plan_gate`) load
    their own dependencies (`_common_agy`, `_config`) without conflicting
    with Claude Code hooks sharing the same module names.
    """
    if name in _AGY_MODULE_CACHE:
        return _AGY_MODULE_CACHE[name]

    mod_name = f"agy_{name}"
    file_path = AGY_HOOKS_DIR / f"{name}.py"
    if not file_path.is_file():
        raise ImportError(f"Antigravity hook file does not exist: {file_path}")

    # Preload dependencies in cache first
    if name != "_common_agy" and "_common_agy" not in _AGY_MODULE_CACHE:
        load_agy_module("_common_agy")
    if name not in ("_common_agy", "_config") and "_config" not in _AGY_MODULE_CACHE:
        load_agy_module("_config")

    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {name} from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    _AGY_MODULE_CACHE[name] = module

    # Save previous state of conflicting names
    old_config = sys.modules.get("_config")
    old_common = sys.modules.get("_common_agy")
    old_path = list(sys.path)

    # Point local references to Antigravity modules during execution
    sys.modules["_common_agy"] = _AGY_MODULE_CACHE.get("_common_agy", module)
    sys.modules["_config"] = _AGY_MODULE_CACHE.get("_config", module)
    if str(AGY_HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(AGY_HOOKS_DIR))

    try:
        spec.loader.exec_module(module)
    finally:
        # Restore sys.modules and sys.path
        if old_config is not None:
            sys.modules["_config"] = old_config
        else:
            sys.modules.pop("_config", None)

        if old_common is not None:
            sys.modules["_common_agy"] = old_common
        else:
            sys.modules.pop("_common_agy", None)

        sys.path[:] = old_path

    return module


def invoke_hook_main(
    module: Any,
    payload: dict[str, Any] | None = None,
    raw_stdin: str | None = None,
    allow_non_zero_exit: bool = False,
) -> tuple[dict[str, Any] | None, str, str]:
    """Execute module.main() intercepting stdin, stdout, stderr, and sys.exit.

    Returns:
        tuple of (parsed_json_output, raw_stdout, raw_stderr)
    """
    if raw_stdin is None:
        raw_stdin = json.dumps(payload) if payload is not None else ""

    old_stdin = sys.stdin
    stdin_buf = StringIO(raw_stdin)
    stdout_buf = StringIO()
    stderr_buf = StringIO()

    exit_code = 0
    sys.stdin = stdin_buf

    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        try:
            module.main()
        except SystemExit as exc:
            exit_code = (
                exc.code
                if isinstance(exc.code, int)
                else (0 if exc.code is None else 1)
            )
        finally:
            sys.stdin = old_stdin

    if not allow_non_zero_exit:
        assert exit_code == 0, (
            f"Hook {module.__name__} exited with non-zero code {exit_code}.\n"
            f"Stdout: {stdout_buf.getvalue()}\nStderr: {stderr_buf.getvalue()}"
        )

    out_str = stdout_buf.getvalue()
    err_str = stderr_buf.getvalue()

    parsed = None
    if out_str.strip():
        try:
            parsed = json.loads(out_str.strip())
        except (json.JSONDecodeError, ValueError):
            parsed = None

    return parsed, out_str, err_str


def create_test_git_repo(
    target_dir: Path | None = None, default_branch: str = "main"
) -> Path:
    """Create and initialize a temporary git repository with a default
    branch and commit.
    """
    if target_dir is None:
        repo_dir = Path(tempfile.mkdtemp(prefix="canon_test_repo_"))
    else:
        repo_dir = target_dir
        repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "init", "-b", default_branch],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Canon Tester"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tester@example.com"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    readme = repo_dir / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    return repo_dir


def make_pre_tool_payload(
    tool_name: str,
    args: dict[str, Any],
    workspace: Path | str | None = None,
    conversation_id: str = "conv-test-123",
    artifact_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Generate an Antigravity PreToolUse hook payload."""
    payload: dict[str, Any] = {
        "workspacePaths": [str(workspace)] if workspace else [],
        "conversationId": conversation_id,
        "artifactDirectoryPath": str(artifact_dir) if artifact_dir else "",
        "toolCall": {
            "name": tool_name,
            "args": args,
        },
    }
    return payload


def make_post_tool_payload(
    tool_name: str,
    args: dict[str, Any],
    workspace: Path | str | None = None,
    conversation_id: str = "conv-test-123",
    artifact_dir: Path | str | None = None,
    error: str | None = None,
    tool_response: Any = None,
) -> dict[str, Any]:
    """Generate an Antigravity PostToolUse hook payload."""
    payload: dict[str, Any] = {
        "workspacePaths": [str(workspace)] if workspace else [],
        "conversationId": conversation_id,
        "artifactDirectoryPath": str(artifact_dir) if artifact_dir else "",
        "toolCall": {
            "name": tool_name,
            "args": args,
        },
    }
    if error is not None:
        payload["error"] = error
    if tool_response is not None:
        payload["tool_response"] = tool_response
    return payload


def make_pre_invocation_payload(
    invocation_num: int = 0,
    source: str | None = None,
    is_compact: bool = False,
    workspace: Path | str | None = None,
    conversation_id: str = "conv-test-123",
    artifact_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Generate an Antigravity PreInvocation hook payload."""
    payload: dict[str, Any] = {
        "invocationNum": invocation_num,
        "workspacePaths": [str(workspace)] if workspace else [],
        "conversationId": conversation_id,
        "artifactDirectoryPath": str(artifact_dir) if artifact_dir else "",
        "isCompacted": is_compact,
    }
    if source is not None:
        payload["source"] = source
    return payload


def make_stop_payload(
    workspace: Path | str | None = None,
    conversation_id: str = "conv-test-123",
    artifact_dir: Path | str | None = None,
    execution_num: int = 1,
    stop_hook_active: bool = False,
) -> dict[str, Any]:
    """Generate an Antigravity Stop hook payload."""
    return {
        "workspacePaths": [str(workspace)] if workspace else [],
        "conversationId": conversation_id,
        "artifactDirectoryPath": str(artifact_dir) if artifact_dir else "",
        "executionNum": execution_num,
        "stop_hook_active": stop_hook_active,
    }


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Fixture providing a clean initialized Git repo."""
    repo_dir = tmp_path / "repo"
    return create_test_git_repo(repo_dir)


@pytest.fixture
def temp_scratchpad(tmp_path: Path) -> Path:
    """Fixture providing an Antigravity scratchpad path
    (`artifactDirectoryPath / conversationId / canon`).
    """
    scratchpad = tmp_path / "artifacts" / "conv-test-123" / "canon"
    scratchpad.mkdir(parents=True, exist_ok=True)
    return scratchpad
