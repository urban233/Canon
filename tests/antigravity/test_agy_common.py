# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/hooks/_common_agy.py."""

from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.antigravity.conftest import create_test_git_repo, load_agy_module

_common = load_agy_module("_common_agy")


class ReadPayloadTests(unittest.TestCase):
    def test_valid_dict_parsed(self) -> None:
        payload = {"workspacePaths": ["/path/to/repo"], "conversationId": "conv-1"}
        with patch("sys.stdin", StringIO(json.dumps(payload))):
            self.assertEqual(_common.read_payload(), payload)

    def test_empty_stdin_returns_none(self) -> None:
        with patch("sys.stdin", StringIO("")):
            self.assertIsNone(_common.read_payload())

    def test_whitespace_stdin_returns_none(self) -> None:
        with patch("sys.stdin", StringIO("   \n\t  \n")):
            self.assertIsNone(_common.read_payload())

    def test_malformed_json_returns_none(self) -> None:
        with patch("sys.stdin", StringIO("{unclosed_json: ")):
            self.assertIsNone(_common.read_payload())

    def test_non_dict_json_returns_none(self) -> None:
        for non_dict in ('"just a string"', "12345", "[1, 2, 3]", "true", "null"):
            with patch("sys.stdin", StringIO(non_dict)):
                self.assertIsNone(_common.read_payload())


class RepoRootTests(unittest.TestCase):
    def test_prefers_workspace_paths_first_element(self) -> None:
        payload = {"workspacePaths": ["/custom/workspace", "/second/workspace"]}
        self.assertEqual(_common.repo_root(payload), Path("/custom/workspace"))

    def test_fallback_to_cwd_key_when_workspace_paths_empty(self) -> None:
        payload = {"workspacePaths": [], "cwd": "/fallback/cwd"}
        self.assertEqual(_common.repo_root(payload), Path("/fallback/cwd"))

    def test_fallback_to_cwd_key_when_workspace_paths_absent(self) -> None:
        payload = {"cwd": "/fallback/cwd"}
        self.assertEqual(_common.repo_root(payload), Path("/fallback/cwd"))

    def test_fallback_to_git_rev_parse_when_payload_none(self) -> None:
        temp_repo = create_test_git_repo()
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["git", "rev-parse", "--show-toplevel"],
                    returncode=0,
                    stdout=f"{temp_repo}\n",
                    stderr="",
                )
                self.assertEqual(_common.repo_root(None), temp_repo)
        finally:
            import shutil

            shutil.rmtree(temp_repo, ignore_errors=True)

    def test_fallback_to_os_cwd_when_git_fails(self) -> None:
        with patch("subprocess.run", side_effect=OSError("git not found")):
            self.assertEqual(_common.repo_root(None), Path.cwd())


class HasWorkspaceTests(unittest.TestCase):
    def test_returns_true_for_valid_workspace_path(self) -> None:
        self.assertTrue(_common.has_workspace({"workspacePaths": ["/some/repo"]}))

    def test_returns_false_for_empty_list(self) -> None:
        self.assertFalse(_common.has_workspace({"workspacePaths": []}))

    def test_returns_false_for_none_payload(self) -> None:
        self.assertFalse(_common.has_workspace(None))

    def test_returns_false_for_non_string_first_element(self) -> None:
        self.assertFalse(_common.has_workspace({"workspacePaths": [123]}))

    def test_returns_false_for_whitespace_first_element(self) -> None:
        self.assertFalse(_common.has_workspace({"workspacePaths": ["   "]}))


class StateDirTests(unittest.TestCase):
    def test_resolves_standard_hierarchy(self) -> None:
        payload = {
            "artifactDirectoryPath": "/var/artifacts",
            "conversationId": "session-42",
        }
        expected = Path("/var/artifacts/session-42/canon")
        self.assertEqual(_common.state_dir(payload), expected)

    def test_custom_subdir(self) -> None:
        payload = {
            "artifactDirectoryPath": "/var/artifacts",
            "conversationId": "session-42",
        }
        expected = Path("/var/artifacts/session-42/custom")
        self.assertEqual(_common.state_dir(payload, subdir="custom"), expected)

    def test_returns_none_on_missing_artifact_dir(self) -> None:
        payload = {"conversationId": "session-42"}
        self.assertIsNone(_common.state_dir(payload))

    def test_returns_none_on_missing_conversation_id(self) -> None:
        payload = {"artifactDirectoryPath": "/var/artifacts"}
        self.assertIsNone(_common.state_dir(payload))

    def test_returns_none_on_none_payload(self) -> None:
        self.assertIsNone(_common.state_dir(None))

    def test_legacy_scratchpad_fallback(self) -> None:
        payload = {"scratchpad_dir": "/tmp/legacy/scratch"}
        expected = Path("/tmp/legacy/scratch/canon")
        self.assertEqual(_common.state_dir(payload), expected)


class ToolAccessorsTests(unittest.TestCase):
    def test_tool_call_extraction(self) -> None:
        tc = {"name": "run_command", "args": {"CommandLine": "ls"}}
        self.assertEqual(_common.tool_call({"toolCall": tc}), tc)
        self.assertIsNone(_common.tool_call({}))
        self.assertIsNone(_common.tool_call(None))

    def test_tool_name_from_tool_call(self) -> None:
        payload = {"toolCall": {"name": "replace_file_content"}}
        self.assertEqual(_common.tool_name(payload), "replace_file_content")

    def test_tool_name_from_top_level_fallback(self) -> None:
        payload = {"tool_name": "write_to_file"}
        self.assertEqual(_common.tool_name(payload), "write_to_file")

    def test_tool_name_returns_none_when_absent(self) -> None:
        self.assertIsNone(_common.tool_name({}))
        self.assertIsNone(_common.tool_name(None))

    def test_tool_args_from_tool_call(self) -> None:
        args = {"TargetFile": "a.txt", "CodeContent": "hi"}
        payload = {"toolCall": {"args": args}}
        self.assertEqual(_common.tool_args(payload), args)

    def test_tool_args_from_top_level_fallback(self) -> None:
        args = {"command": "echo 1"}
        payload = {"tool_input": args}
        self.assertEqual(_common.tool_args(payload), args)

    def test_tool_args_returns_empty_dict_when_absent(self) -> None:
        self.assertEqual(_common.tool_args({}), {})
        self.assertEqual(_common.tool_args(None), {})

    def test_tool_command_variants(self) -> None:
        self.assertEqual(
            _common.tool_command({"toolCall": {"args": {"CommandLine": "git status"}}}),
            "git status",
        )
        self.assertEqual(
            _common.tool_command({"toolCall": {"args": {"command": "make test"}}}),
            "make test",
        )
        self.assertEqual(
            _common.tool_command({"toolCall": {"args": {"cmd": "pytest"}}}),
            "pytest",
        )
        self.assertIsNone(_common.tool_command({"toolCall": {"args": {}}}))

    def test_tool_target_file_variants(self) -> None:
        self.assertEqual(
            _common.tool_target_file(
                {"toolCall": {"args": {"TargetFile": "src/foo.py"}}}
            ),
            "src/foo.py",
        )
        self.assertEqual(
            _common.tool_target_file(
                {"toolCall": {"args": {"target_file": "src/bar.py"}}}
            ),
            "src/bar.py",
        )
        self.assertEqual(
            _common.tool_target_file(
                {"toolCall": {"args": {"filePath": "src/baz.py"}}}
            ),
            "src/baz.py",
        )
        self.assertIsNone(_common.tool_target_file({"toolCall": {"args": {}}}))

    def test_tool_code_content_variants(self) -> None:
        self.assertEqual(
            _common.tool_code_content(
                {"toolCall": {"args": {"CodeContent": "print(1)"}}}
            ),
            "print(1)",
        )
        self.assertEqual(
            _common.tool_code_content(
                {"toolCall": {"args": {"code_content": "print(2)"}}}
            ),
            "print(2)",
        )
        self.assertEqual(
            _common.tool_code_content({"toolCall": {"args": {"content": "print(3)"}}}),
            "print(3)",
        )
        self.assertIsNone(_common.tool_code_content({"toolCall": {"args": {}}}))


class OutputEmittersTests(unittest.TestCase):
    def _capture_emitter(self, fn, *args, **kwargs) -> tuple[dict[str, Any], int]:
        out = StringIO()
        exit_code = 0
        with redirect_stdout(out):
            try:
                fn(*args, **kwargs)
            except SystemExit as exc:
                exit_code = (
                    exc.code
                    if isinstance(exc.code, int)
                    else (0 if exc.code is None else 1)
                )
        parsed = json.loads(out.getvalue().strip())
        return parsed, exit_code

    def test_allow_clean(self) -> None:
        parsed, code = self._capture_emitter(_common.allow)
        self.assertEqual(code, 0)
        self.assertEqual(parsed, {"decision": "allow"})

    def test_allow_with_reason(self) -> None:
        parsed, code = self._capture_emitter(_common.allow, reason="ok")
        self.assertEqual(code, 0)
        self.assertEqual(parsed, {"decision": "allow", "reason": "ok"})

    def test_allow_with_overwrite(self) -> None:
        parsed, code = self._capture_emitter(
            _common.allow, overwrite={"CommandLine": "git commit -m 'clean'"}
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            parsed,
            {
                "decision": "allow",
                "overwrite": {"CommandLine": "git commit -m 'clean'"},
            },
        )

    def test_deny(self) -> None:
        parsed, code = self._capture_emitter(
            _common.deny, "destructive command blocked"
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            parsed, {"decision": "deny", "reason": "destructive command blocked"}
        )

    def test_ask(self) -> None:
        parsed, code = self._capture_emitter(_common.ask, "confirm edit on main")
        self.assertEqual(code, 0)
        self.assertEqual(parsed, {"decision": "ask", "reason": "confirm edit on main"})

    def test_continue_turn(self) -> None:
        parsed, code = self._capture_emitter(_common.continue_turn, "tests failed")
        self.assertEqual(code, 0)
        self.assertEqual(parsed, {"decision": "continue", "reason": "tests failed"})

    def test_pass_stop(self) -> None:
        parsed, code = self._capture_emitter(_common.pass_stop)
        self.assertEqual(code, 0)
        self.assertEqual(parsed, {})

    def test_pass_post_tool(self) -> None:
        parsed, code = self._capture_emitter(_common.pass_post_tool)
        self.assertEqual(code, 0)
        self.assertEqual(parsed, {})

    def test_inject_context_non_empty(self) -> None:
        parsed, code = self._capture_emitter(
            _common.inject_context, "Canon position: branch main"
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            parsed,
            {"injectSteps": [{"ephemeralMessage": "Canon position: branch main"}]},
        )

    def test_inject_context_empty(self) -> None:
        parsed, code = self._capture_emitter(_common.inject_context, "")
        self.assertEqual(code, 0)
        self.assertEqual(parsed, {"injectSteps": []})


class FailOpenDecoratorTests(unittest.TestCase):
    def test_fail_open_catches_exception_and_exits_zero(self) -> None:
        out = StringIO()
        err = StringIO()

        @_common.fail_open
        def broken_main() -> None:
            raise ValueError("Something unexpected broke inside the hook")

        exit_code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                broken_main()
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else 0

        self.assertEqual(exit_code, 0)
        # Default fallback is allow
        parsed = json.loads(out.getvalue().strip())
        self.assertEqual(parsed, {"decision": "allow"})
        self.assertIn("failing open", err.getvalue())

    def test_fail_open_with_custom_fallback_fn(self) -> None:
        out = StringIO()
        err = StringIO()

        @_common.fail_open(fallback_fn=_common.pass_stop)
        def broken_stop() -> None:
            raise RuntimeError("Stop hook failure")

        exit_code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                broken_stop()
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else 0

        self.assertEqual(exit_code, 0)
        parsed = json.loads(out.getvalue().strip())
        self.assertEqual(parsed, {})
        self.assertIn("Stop hook failure", err.getvalue())

    def test_fail_open_preserves_clean_exit(self) -> None:
        out = StringIO()
        err = StringIO()

        @_common.fail_open
        def clean_main() -> None:
            _common.deny("explicit denial")

        exit_code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                clean_main()
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else 0

        self.assertEqual(exit_code, 0)
        parsed = json.loads(out.getvalue().strip())
        self.assertEqual(parsed, {"decision": "deny", "reason": "explicit denial"})
        self.assertEqual(err.getvalue(), "")


class GitAndPlanParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.repo, ignore_errors=True)

    def test_current_branch_and_default_branch(self) -> None:
        self.assertEqual(_common.current_branch(self.repo), "main")
        self.assertEqual(_common.default_branch(self.repo), "main")

    def test_merge_base_and_head_sha(self) -> None:
        head = _common.head_sha(self.repo)
        self.assertIsNotNone(head)
        self.assertEqual(len(head), 9)
        base = _common.merge_base(self.repo, "main")
        self.assertEqual(base, head)

    def test_log_decision_and_last_decision(self) -> None:
        _common.log_decision(
            self.repo, "test_hook", "allow", reason="all good", extra={"key": "val"}
        )
        rec = _common.last_decision(self.repo, "test_hook")
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["hook"], "test_hook")
        self.assertEqual(rec["decision"], "allow")
        self.assertEqual(rec["reason"], "all good")
        self.assertEqual(rec["key"], "val")
        self.assertIn("T", rec["timestamp"])

    def test_plan_sections_parsing(self) -> None:
        text = (
            "Intro paragraph\n\n"
            "## Scope\n[src/**, tests/**]\n\n"
            "## Non-goals\n* Do not refactor auth\n\n"
            "## Done\nAll tests pass.\n"
        )
        sections = _common.plan_sections(text)
        self.assertEqual(sections["scope"], "[src/**, tests/**]")
        self.assertEqual(sections["non-goals"], "* Do not refactor auth")
        self.assertEqual(sections["done"], "All tests pass.")

    def test_plan_header_and_body_parsing(self) -> None:
        plan_text = (
            "---\n"
            "status: approved\n"
            "base: abcdef123\n"
            'done: "Everything is complete"\n'
            "---\n\n"
            "# My Plan\n\n"
            "## Scope\n[src/**]\n"
        )
        header, body = _common.plan_header_and_body(plan_text)
        self.assertEqual(header["status"], "approved")
        self.assertEqual(header["base"], "abcdef123")
        self.assertEqual(header["done"], "Everything is complete")
        self.assertTrue(body.startswith("# My Plan"))


if __name__ == "__main__":
    unittest.main()
