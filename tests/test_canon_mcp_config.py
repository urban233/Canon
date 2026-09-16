# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_config.py.

`interaction_mode` and the compound-command validator
(`shell_metacharacter`, `verify_command_problem`) get dedicated direct
tests here. The validator tests mirror
tests/test_claude_hooks_config.py's `ShellMetacharacterTests` and
`VerifyCommandProblemTests` exactly, because this module is a
byte-for-byte-in-logic duplicate of plugins/claude/hooks/_config.py
(see this module's docstring) and the two must never quietly drift. The
rest of this module (`load_config`, `has_verification_signal`) is
already exercised indirectly, via mocking, in
`test_canon_mcp_evidence.py` and `test_canon_mcp_position.py`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from canon_mcp import _config


class ShellMetacharacterTests(unittest.TestCase):
    def test_double_ampersand_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("ruff check . && pytest"), "&&")

    def test_double_pipe_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("ruff check . || pytest"), "||")

    def test_single_pipe_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("echo a | grep b"), "|")

    def test_semicolon_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("echo a; echo b"), ";")

    def test_redirect_out_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("echo a > out.txt"), ">")

    def test_redirect_in_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("echo a < in.txt"), "<")

    def test_unquoted_backtick_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("echo `whoami`"), "`")

    def test_unquoted_command_substitution_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("echo $(whoami)"), "$(")

    def test_unquoted_newline_is_detected(self) -> None:
        self.assertEqual(_config.shell_metacharacter("ruff check .\npytest"), "\n")

    def test_plain_command_has_no_metacharacter(self) -> None:
        self.assertIsNone(_config.shell_metacharacter("just test"))

    def test_pytest_dash_k_with_and_is_not_a_metacharacter(self) -> None:
        """The near miss: no operator character appears anywhere in this
        string, but a word-level scan for "and"/"or" could get confused
        by the word "and" inside the quotes. It must read clean."""
        self.assertIsNone(_config.shell_metacharacter('pytest -k "a and b"'))

    def test_quoted_pipe_is_not_a_metacharacter(self) -> None:
        """The near miss the task exists to get right: a naive substring
        scan for "|" would flag this, but the pipe is single-quoted
        argument content, not an operator."""
        self.assertIsNone(_config.shell_metacharacter("just test --flag='a|b'"))

    def test_quoted_backtick_is_not_a_metacharacter(self) -> None:
        self.assertIsNone(_config.shell_metacharacter('echo "`whoami`"'))

    def test_a_wholly_quoted_command_substitution_is_rejected_conservatively(
        self,
    ) -> None:
        """See plugins/claude/hooks/_config.py's identical test for the
        full reasoning: `$(` can't use the "every character is an
        operator character" rule, so a token that is entirely
        `"$(...)"` is treated as unsafe even when quoted."""
        self.assertEqual(_config.shell_metacharacter('echo "$(whoami)"'), "$(")

    def test_a_prefixed_quoted_command_substitution_is_not_a_metacharacter(
        self,
    ) -> None:
        self.assertIsNone(_config.shell_metacharacter('just check --flags="$(x)"'))

    def test_unterminated_quote_is_not_reported_as_a_metacharacter(self) -> None:
        self.assertIsNone(_config.shell_metacharacter('unterminated "quote'))

    # The blind spots an independent review found in the first version of
    # this function -- see plugins/claude/hooks/_config.py's identical
    # tests for the full reasoning behind each one.

    def test_stderr_redirect_to_stdout_is_detected(self) -> None:
        self.assertIsNotNone(_config.shell_metacharacter("pytest 2>&1"))

    def test_backgrounding_with_more_after_it_is_detected(self) -> None:
        self.assertIsNotNone(_config.shell_metacharacter("ruff check . & pytest"))

    def test_trailing_backgrounding_is_detected(self) -> None:
        self.assertIsNotNone(_config.shell_metacharacter("pytest &"))

    def test_append_redirect_is_detected(self) -> None:
        self.assertIsNotNone(_config.shell_metacharacter("pytest >> log"))

    def test_combined_redirect_is_detected(self) -> None:
        self.assertIsNotNone(_config.shell_metacharacter("pytest &> log"))
        self.assertIsNotNone(_config.shell_metacharacter("pytest 1>&2"))

    def test_operator_after_a_hash_is_still_detected(self) -> None:
        self.assertIsNotNone(_config.shell_metacharacter("just test # && ruff check ."))

    # Required accepts pinned explicitly so a future tightening of the
    # operator rule can't silently break them.

    def test_process_substitution_is_not_rejected(self) -> None:
        self.assertIsNone(_config.shell_metacharacter("cmd <(foo)"))

    def test_pytest_dash_m_with_parens_is_not_rejected(self) -> None:
        self.assertIsNone(_config.shell_metacharacter('pytest -m "not (slow or net)"'))

    def test_bazel_test_output_errors_is_not_rejected(self) -> None:
        self.assertIsNone(
            _config.shell_metacharacter("bazel test //... --test_output=errors")
        )

    def test_a_wholly_quoted_operator_only_argument_is_rejected_conservatively(
        self,
    ) -> None:
        """See plugins/claude/hooks/_config.py's identical test for the
        full reasoning: shlex strips quotes before this function ever
        sees the token, so `cmd "|"` and a bare `cmd |` arrive as the
        same token. Pinned so a future change that makes this accept
        has to argue with a named test."""
        self.assertIsNotNone(_config.shell_metacharacter('cmd "|"'))
        self.assertIsNotNone(_config.shell_metacharacter("cmd '&&'"))


class VerifyCommandProblemTests(unittest.TestCase):
    def test_plain_command_has_no_problem(self) -> None:
        self.assertIsNone(_config.verify_command_problem("pytest"))

    def test_pytest_dash_k_with_and_has_no_problem(self) -> None:
        self.assertIsNone(_config.verify_command_problem('pytest -k "a and b"'))

    def test_quoted_pipe_has_no_problem(self) -> None:
        self.assertIsNone(_config.verify_command_problem("just test --flag='a|b'"))

    def test_compound_command_names_the_operator(self) -> None:
        problem = _config.verify_command_problem("ruff check . && pytest")
        self.assertIsNotNone(problem)
        assert problem is not None
        self.assertIn("&&", problem)

    def test_unterminated_quote_is_a_problem(self) -> None:
        problem = _config.verify_command_problem('unterminated "quote')
        self.assertIsNotNone(problem)
        assert problem is not None
        self.assertIn("could not parse", problem)

    def _assert_named_operator_appears_in_the_explanation(self, command: str) -> None:
        """See plugins/claude/hooks/_config.py's identical test for the
        full reasoning behind this regression check."""
        metacharacter = _config.shell_metacharacter(command)
        assert metacharacter is not None
        problem = _config.verify_command_problem(command)
        assert problem is not None
        prefix = f"this command contains `{metacharacter}`, "
        self.assertTrue(problem.startswith(prefix))
        explanation = problem[len(prefix) :]
        self.assertIn(metacharacter, explanation)

    def test_stderr_redirect_operator_appears_in_the_explanation(self) -> None:
        self._assert_named_operator_appears_in_the_explanation("pytest 2>&1")

    def test_lone_ampersand_operator_appears_in_the_explanation(self) -> None:
        self._assert_named_operator_appears_in_the_explanation("ruff check . & pytest")

    def test_append_redirect_operator_appears_in_the_explanation(self) -> None:
        self._assert_named_operator_appears_in_the_explanation("pytest >> log")

    def test_advice_is_conditional_on_being_a_sequence(self) -> None:
        problem = _config.verify_command_problem("pytest 2>&1")
        assert problem is not None
        self.assertIn("if the real answer is a sequence", problem.lower())


class VerifyCommandSourceTests(unittest.TestCase):
    """See plugins/claude/hooks/_config.py's identical tests: a caller
    reporting a problem with the resolved command must name the file a
    human should actually go edit."""

    def test_defaults_to_the_config_file_with_no_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                _config.verify_command_source(
                    Path(tmp), "feature/widget", {"verify": "just test"}
                ),
                ".canon/config.json",
            )

    def test_defaults_to_the_config_file_with_no_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                _config.verify_command_source(Path(tmp), None, {"verify": "x"}),
                ".canon/config.json",
            )

    def test_names_the_plan_file_when_the_header_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / ".canon" / "plans"
            plan.mkdir(parents=True)
            (plan / "wip.md").write_text(
                '---\nstatus: approved\nverify: "ruff check . && pytest"\n---\n\n'
                "## Approach\nx\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _config.verify_command_source(root, "wip", {"verify": "just test"}),
                ".canon/plans/wip.md",
            )

    def test_a_blank_header_falls_back_to_the_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / ".canon" / "plans"
            plan.mkdir(parents=True)
            (plan / "wip.md").write_text(
                '---\nstatus: approved\nverify: ""\n---\n\n## Approach\nx\n',
                encoding="utf-8",
            )
            self.assertEqual(
                _config.verify_command_source(root, "wip", {"verify": "just test"}),
                ".canon/config.json",
            )


class InteractionModeTests(unittest.TestCase):
    def test_defaults_to_solo_when_no_config(self) -> None:
        self.assertEqual(_config.interaction_mode(None), "solo")

    def test_defaults_to_solo_when_key_absent(self) -> None:
        self.assertEqual(_config.interaction_mode({}), "solo")

    def test_defaults_to_solo_on_an_unrecognized_value(self) -> None:
        self.assertEqual(_config.interaction_mode({"mode": "yolo"}), "solo")

    def test_reads_pair(self) -> None:
        self.assertEqual(_config.interaction_mode({"mode": "pair"}), "pair")

    def test_reads_async(self) -> None:
        self.assertEqual(_config.interaction_mode({"mode": "async"}), "async")


if __name__ == "__main__":
    unittest.main()
