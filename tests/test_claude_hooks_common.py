# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/_common.py.

Covers the fail-open path (a hook that raises still exits 0), malformed
stdin, and the exact JSON each output shape produces -- the properties
Step 1's plan calls out as non-negotiable for this module.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import _common


class ReadPayloadTests(unittest.TestCase):
    def test_parses_a_valid_object(self) -> None:
        with mock.patch.object(sys, "stdin", io.StringIO('{"cwd": "/repo"}')):
            self.assertEqual(_common.read_payload(), {"cwd": "/repo"})

    def test_returns_none_on_empty_stdin(self) -> None:
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            self.assertIsNone(_common.read_payload())

    def test_returns_none_on_invalid_json(self) -> None:
        with mock.patch.object(sys, "stdin", io.StringIO("{not json")):
            self.assertIsNone(_common.read_payload())

    def test_returns_none_on_non_object_json(self) -> None:
        with mock.patch.object(sys, "stdin", io.StringIO("[1, 2, 3]")):
            self.assertIsNone(_common.read_payload())


class RepoRootTests(unittest.TestCase):
    def test_prefers_cwd_from_payload(self) -> None:
        self.assertEqual(_common.repo_root({"cwd": "/some/repo"}), Path("/some/repo"))

    def test_falls_back_to_git_when_payload_is_none(self) -> None:
        completed = mock.Mock(returncode=0, stdout="/git/root\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_common.repo_root(None), Path("/git/root"))

    def test_falls_back_to_git_when_cwd_missing(self) -> None:
        completed = mock.Mock(returncode=0, stdout="/git/root\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_common.repo_root({}), Path("/git/root"))

    def test_falls_back_to_cwd_when_git_fails(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_common.repo_root(None), Path.cwd())

    def test_falls_back_to_cwd_when_git_is_unreachable(self) -> None:
        with mock.patch("subprocess.run", side_effect=OSError("no git")):
            self.assertEqual(_common.repo_root(None), Path.cwd())

    def test_falls_back_to_cwd_when_git_times_out(self) -> None:
        import subprocess

        with mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            self.assertEqual(_common.repo_root(None), Path.cwd())


def _captured_json(func: Callable[..., None], *args: Any) -> dict[str, Any]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        with mock.patch("sys.exit") as exit_mock:
            func(*args)
    exit_mock.assert_called_once_with(0)
    return json.loads(buffer.getvalue())


class OutputShapeTests(unittest.TestCase):
    def test_allow_exits_zero_with_no_output(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            with mock.patch("sys.exit") as exit_mock:
                _common.allow()
        exit_mock.assert_called_once_with(0)
        self.assertEqual(buffer.getvalue(), "")

    def test_ask_shape(self) -> None:
        payload = _captured_json(_common.ask, "needs a plan first")
        self.assertEqual(
            payload,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": "needs a plan first",
                }
            },
        )

    def test_deny_shape(self) -> None:
        payload = _captured_json(_common.deny, "no interactive terminal")
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecisionReason"],
            "no interactive terminal",
        )

    def test_block_shape(self) -> None:
        payload = _captured_json(_common.block, "verification failed")
        self.assertEqual(
            payload, {"decision": "block", "reason": "verification failed"}
        )

    def test_context_shape(self) -> None:
        payload = _captured_json(_common.context, "SessionStart", "hello")
        self.assertEqual(
            payload,
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "hello",
                }
            },
        )


class FailOpenTests(unittest.TestCase):
    def test_lets_a_normal_hook_run(self) -> None:
        calls = []
        wrapped = _common.fail_open(lambda: calls.append("ran"))
        wrapped()
        self.assertEqual(calls, ["ran"])

    def test_swallows_an_unhandled_exception_and_exits_zero(self) -> None:
        def boom() -> None:
            raise RuntimeError("hook bug")

        wrapped = _common.fail_open(boom)
        with mock.patch("sys.exit") as exit_mock:
            wrapped()
        exit_mock.assert_called_once_with(0)

    def test_preserves_an_explicit_sys_exit(self) -> None:
        def calls_exit() -> None:
            sys.exit(0)

        wrapped = _common.fail_open(calls_exit)
        with self.assertRaises(SystemExit) as caught:
            wrapped()
        self.assertEqual(caught.exception.code, 0)


class LogDecisionTests(unittest.TestCase):
    def test_writes_one_gitignored_jsonl_line(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _common.log_decision(root, "require_plan.py", "ask", reason="no plan yet")
            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            self.assertTrue(log_path.exists())
            record = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["hook"], "require_plan.py")
            self.assertEqual(record["decision"], "ask")
            self.assertEqual(record["reason"], "no plan yet")
            self.assertIn("timestamp", record)

    def test_appends_rather_than_overwrites(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _common.log_decision(root, "a.py", "allow")
            _common.log_decision(root, "b.py", "ask", reason="second")
            lines = (
                (root / ".canon" / "hooks" / "decisions.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            self.assertEqual(len(lines), 2)

    def test_never_raises_when_the_path_is_unwritable(self) -> None:
        # A path under a file (not a directory) cannot be mkdir'd into.
        import tempfile

        with tempfile.NamedTemporaryFile() as blocked_file:
            root = Path(blocked_file.name)
            try:
                _common.log_decision(root, "a.py", "allow")
            except OSError:
                self.fail("log_decision must never raise")


class GitDerivationTests(unittest.TestCase):
    def test_current_branch_returns_trimmed_output(self) -> None:
        completed = mock.Mock(returncode=0, stdout="feature/widget\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_common.current_branch(Path("/repo")), "feature/widget")

    def test_current_branch_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_common.current_branch(Path("/repo")))

    def test_current_branch_returns_none_when_git_is_unreachable(self) -> None:
        with mock.patch("subprocess.run", side_effect=OSError("no git")):
            self.assertIsNone(_common.current_branch(Path("/repo")))

    def test_default_branch_strips_origin_prefix(self) -> None:
        completed = mock.Mock(returncode=0, stdout="origin/develop\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_common.default_branch(Path("/repo")), "develop")

    def test_default_branch_falls_back_to_main_without_a_remote(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_common.default_branch(Path("/repo")), "main")

    def test_merge_base_returns_a_short_sha(self) -> None:
        completed = mock.Mock(returncode=0, stdout="abcdef0123456789\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_common.merge_base(Path("/repo"), "main"), "abcdef012")

    def test_merge_base_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=1, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_common.merge_base(Path("/repo"), "main"))


if __name__ == "__main__":
    unittest.main()
