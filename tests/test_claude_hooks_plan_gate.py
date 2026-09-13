# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/plan_gate.py.

Real throwaway git repos via subprocess, mirroring
test_claude_hooks_check_scope.py's `_init_repo`/`_invoke_main` style.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import plan_gate


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _init_repo(root: Path, branch: str) -> None:
    _run_git(root, "init", "-q")
    _run_git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _run_git(
        root,
        "-c",
        "user.email=canon@example.com",
        "-c",
        "user.name=Canon Tests",
        "commit",
        "--allow-empty",
        "-m",
        "init",
    )
    if branch != "main":
        _run_git(root, "checkout", "-q", "-b", branch)


def _write_plan(root: Path, branch: str) -> None:
    plan_path = root / ".canon" / "plans" / f"{branch}.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\nstatus: approved\n---\n\n## Approach\nx\n", "utf-8")


def _write_config(root: Path, config: dict[str, Any]) -> None:
    config_path = root / ".canon" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config), encoding="utf-8")


def _invoke_main(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            with mock.patch("sys.stdout", buffer):
                plan_gate.main()
    return buffer.getvalue()


class EditOrWriteTests(unittest.TestCase):
    def test_asks_on_default_branch_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "a.py")},
                }
            )
            payload = json.loads(output)
            self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "ask")
            self.assertIn(
                "default branch",
                payload["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_asks_on_feature_branch_with_no_plan_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/x")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(root / "a.py")},
                }
            )
            payload = json.loads(output)
            self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "ask")
            self.assertIn(
                "No plan is saved",
                payload["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_allowed_on_feature_branch_with_a_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/x")
            _write_plan(root, "feature/x")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "a.py")},
                }
            )
            self.assertEqual(output, "")

    def test_default_branch_guard_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            _write_plan(root, "main")
            _write_config(root, {"guard_default_branch": False})
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "a.py")},
                }
            )
            self.assertEqual(output, "")


class BashTests(unittest.TestCase):
    def test_asks_nesting_a_branch_under_a_hand_made_one_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/x")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git checkout -b feature/y"},
                }
            )
            payload = json.loads(output)
            self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "ask")
            self.assertIn(
                "adopt it", payload["hookSpecificOutput"]["permissionDecisionReason"]
            )

    def test_allows_branching_from_the_default_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git switch -c feature/y"},
                }
            )
            self.assertEqual(output, "")

    def test_asks_committing_on_the_default_branch_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": 'git commit -m "wip"'},
                }
            )
            payload = json.loads(output)
            self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "ask")
            self.assertIn(
                "default branch",
                payload["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_allows_committing_on_a_feature_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/x")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": 'git commit -m "wip"'},
                }
            )
            self.assertEqual(output, "")

    def test_allows_unrelated_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status"},
                }
            )
            self.assertEqual(output, "")


class InteractionModeTests(unittest.TestCase):
    def test_async_mode_denies_instead_of_asking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            _write_config(root, {"mode": "async"})
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "a.py")},
                }
            )
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            self.assertEqual(hook_output["permissionDecision"], "deny")
            self.assertIn("default branch", hook_output["permissionDecisionReason"])
            self.assertIn(
                "surface the question above as your final message",
                hook_output["permissionDecisionReason"],
            )

    def test_pair_mode_asks_the_same_as_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            _write_config(root, {"mode": "pair"})
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "a.py")},
                }
            )
            payload = json.loads(output)
            self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "ask")


class MiscTests(unittest.TestCase):
    def test_noop_for_unrelated_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            output = _invoke_main(
                {"cwd": str(root), "tool_name": "Read", "tool_input": {}}
            )
            self.assertEqual(output, "")

    def test_noop_on_empty_stdin(self) -> None:
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            with mock.patch("sys.exit"):
                buffer = io.StringIO()
                with mock.patch("sys.stdout", buffer):
                    plan_gate.main()
                self.assertEqual(buffer.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
