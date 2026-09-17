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
import tempfile
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

    def test_extra_fields_are_merged_into_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _common.log_decision(
                root,
                "reviewer",
                "READY FOR HUMAN APPROVAL",
                extra={"head": "abc1234d"},
            )
            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            record = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["head"], "abc1234d")
            self.assertEqual(record["decision"], "READY FOR HUMAN APPROVAL")

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

    def test_head_sha_returns_a_short_sha(self) -> None:
        completed = mock.Mock(returncode=0, stdout="0123456789abcdef\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_common.head_sha(Path("/repo")), "012345678")

    def test_head_sha_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_common.head_sha(Path("/repo")))


class PlanSectionsTests(unittest.TestCase):
    def test_splits_headings_case_and_whitespace_insensitively(self) -> None:
        body = "# Title\n\n## Approach\nDo it.\n\n## Non-goals\n- Not that.\n"
        sections = _common.plan_sections(body)
        self.assertEqual(sections["approach"], "Do it.")
        self.assertEqual(sections["non-goals"], "- Not that.")

    def test_last_section_runs_to_end_of_body(self) -> None:
        body = "## Verification\n1. Run tests.\n"
        self.assertEqual(_common.plan_sections(body)["verification"], "1. Run tests.")

    def test_no_headings_yields_empty_dict(self) -> None:
        self.assertEqual(_common.plan_sections("just prose, no headings"), {})


class LastDecisionTests(unittest.TestCase):
    def test_returns_none_when_log_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(_common.last_decision(Path(root), "stop.py"))

    def test_returns_the_most_recent_matching_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _common.log_decision(root, "stop.py", "block", reason="first")
            _common.log_decision(root, "other.py", "allow", reason="unrelated")
            _common.log_decision(root, "stop.py", "allow", reason="second")
            record = _common.last_decision(root, "stop.py")
            assert record is not None
            self.assertEqual(record["decision"], "allow")
            self.assertEqual(record["reason"], "second")

    def test_ignores_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            log_path.parent.mkdir(parents=True)
            log_path.write_text("not json\n", encoding="utf-8")
            self.assertIsNone(_common.last_decision(root, "stop.py"))


_SAVED_PLAN = """---
status: approved
base: "a41f0c9"
scope: [src/slugs/**, tests/slugs/**]
done: "duplicate slugs raise, with a regression test"
verify: "just test"
parent:
---

## Approach
Do it.

## Non-goals
- Not that.

## Verification
1. Run tests.
"""


class PlanHeaderAndBodyTests(unittest.TestCase):
    def test_parses_header_and_body(self) -> None:
        header, body = _common.plan_header_and_body(_SAVED_PLAN)
        self.assertEqual(header["status"], "approved")
        self.assertEqual(header["base"], "a41f0c9")
        self.assertEqual(header["scope"], "[src/slugs/**, tests/slugs/**]")
        self.assertEqual(header["verify"], "just test")
        self.assertIn("Do it.", body)

    def test_bare_keys_are_empty_strings(self) -> None:
        header, _ = _common.plan_header_and_body(_SAVED_PLAN)
        self.assertEqual(header["parent"], "")

    def test_escaped_quotes_and_backslashes_round_trip(self) -> None:
        text = '---\nnotes: "a \\"quoted\\" word and a \\\\ backslash"\n---\n\nbody'
        header, _ = _common.plan_header_and_body(text)
        self.assertEqual(header["notes"], 'a "quoted" word and a \\ backslash')

    def test_no_header_block_returns_empty_header_and_whole_text_as_body(self) -> None:
        header, body = _common.plan_header_and_body("## Approach\nHand-written.\n")
        self.assertEqual(header, {})
        self.assertIn("Hand-written.", body)

    def test_parse_header_is_the_header_half_alone(self) -> None:
        self.assertEqual(_common.parse_header(_SAVED_PLAN)["status"], "approved")


class StateDirTests(unittest.TestCase):
    def test_none_when_payload_is_none(self) -> None:
        self.assertIsNone(_common.state_dir(None))

    def test_none_when_scratchpad_dir_missing(self) -> None:
        self.assertIsNone(_common.state_dir({}))

    def test_joins_scratchpad_dir_with_the_default_subdir(self) -> None:
        result = _common.state_dir({"scratchpad_dir": "/scratch"})
        self.assertEqual(result, Path("/scratch") / "canon")

    def test_accepts_a_custom_subdir(self) -> None:
        result = _common.state_dir({"scratchpad_dir": "/scratch"}, "other")
        self.assertEqual(result, Path("/scratch") / "other")


class RunCommandTests(unittest.TestCase):
    """`run_command` reports four independent facts.

    `configuration_fault` and `timed_out` are separate booleans because
    two different callers ask only one of them each: `stop.py` keeps a
    configuration fault out of its refusal budget, and `fast_check.py`
    stays silent on a timeout. Both are reported rather than described,
    so neither caller has to string-match `detail` to tell them apart.
    """

    def test_passes_on_zero_exit(self) -> None:
        result = _common.run_command(Path.cwd(), "true", 30)
        self.assertTrue(result.passed)
        self.assertEqual(result.detail, "")
        self.assertFalse(result.configuration_fault)
        self.assertFalse(result.timed_out)

    def test_fails_on_nonzero_exit_with_output_attached(self) -> None:
        """A genuine failure -- the command ran -- must not be flagged as
        a configuration fault, or `stop.py`'s `main` would silently
        withhold it from the refusal budget the way it does a real
        config problem."""
        result = _common.run_command(
            Path.cwd(), "python3 -c \"import sys; print('boom'); sys.exit(1)\"", 30
        )
        self.assertFalse(result.passed)
        self.assertIn("boom", result.detail)
        self.assertFalse(result.configuration_fault)
        self.assertFalse(result.timed_out)

    def test_fails_on_unparsable_command(self) -> None:
        result = _common.run_command(Path.cwd(), 'unterminated "quote', 30)
        self.assertFalse(result.passed)
        self.assertIn("Could not parse", result.detail)
        self.assertTrue(result.configuration_fault)

    def test_fails_on_missing_executable(self) -> None:
        """A binary that isn't on `PATH` is a configuration fault, not a
        failing check -- previously `stop.py`'s `main` could not tell
        this apart from a genuine red result."""
        result = _common.run_command(Path.cwd(), "canon-nonexistent-command-xyz", 30)
        self.assertFalse(result.passed)
        self.assertIn("Could not run", result.detail)
        self.assertTrue(result.configuration_fault)

    def test_a_timeout_is_reported_as_timed_out_not_as_a_fault(self) -> None:
        """A command that ran and overran is a real, if unfinished,
        answer -- unlike a missing binary, which never started. Only
        `timed_out` is set, and `fast_check.py` depends on that
        distinction to stay silent rather than reporting a build-tool
        lock wait as a regression."""
        result = _common.run_command(Path.cwd(), "sleep 5", 1)
        self.assertFalse(result.passed)
        self.assertIn("timed out", result.detail)
        self.assertFalse(result.configuration_fault)
        self.assertTrue(result.timed_out)


if __name__ == "__main__":
    unittest.main()
