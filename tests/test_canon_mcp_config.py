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

import unittest

from canon_mcp import _config


class ShellMetacharacterTests(unittest.TestCase):
    def test_double_ampersand_is_detected(self) -> None:
        self.assertEqual(
            _config.shell_metacharacter("ruff check . && pytest"), "&&"
        )

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

    def test_unterminated_quote_is_not_reported_as_a_metacharacter(self) -> None:
        self.assertIsNone(_config.shell_metacharacter('unterminated "quote'))


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
