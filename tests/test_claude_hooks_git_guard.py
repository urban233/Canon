# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/git_guard.py."""

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

import git_guard


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)


def _invoke_main(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            with mock.patch("sys.stdout", buffer):
                git_guard.main()
    return buffer.getvalue()


def _payload(root: Path, command: str) -> dict[str, Any]:
    return {
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


class DestructiveCommandTests(unittest.TestCase):
    def _assert_denied(self, command: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            self.assertEqual(
                payload["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_force_push_long_flag(self) -> None:
        self._assert_denied("git push --force origin main")

    def test_force_push_short_flag(self) -> None:
        self._assert_denied("git push -f origin main")

    def test_hard_reset(self) -> None:
        self._assert_denied("git reset --hard HEAD~1")

    def test_forced_clean(self) -> None:
        self._assert_denied("git clean -fd")

    def test_forced_clean_flag_order_reversed(self) -> None:
        self._assert_denied("git clean -df")

    def test_local_branch_delete(self) -> None:
        self._assert_denied("git branch -D feature/x")

    def test_remote_branch_delete_via_push(self) -> None:
        self._assert_denied("git push origin --delete feature/x")

    def test_merge(self) -> None:
        self._assert_denied("git merge feature/x")

    def test_safe_push_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, "git push origin feature/x"))
            self.assertEqual(output, "")

    def test_unrelated_command_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, "git status"))
            self.assertEqual(output, "")


class AttributionStrippingTests(unittest.TestCase):
    def test_strips_a_co_authored_by_trailer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                "git commit -m \"$(cat <<'EOF'\n"
                "feat: thing\n\n"
                "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
                'EOF\n)"'
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", hook_output["updatedInput"]["command"])
            self.assertIn("feat: thing", hook_output["updatedInput"]["command"])

    def test_commit_without_a_trailer_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, 'git commit -m "fix: thing"'))
            self.assertEqual(output, "")


class MiscTests(unittest.TestCase):
    def test_noop_for_unrelated_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(
                {"cwd": str(root), "tool_name": "Read", "tool_input": {}}
            )
            self.assertEqual(output, "")

    def test_noop_when_command_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(
                {"cwd": str(root), "tool_name": "Bash", "tool_input": {}}
            )
            self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
