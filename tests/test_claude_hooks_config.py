# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/_config.py.

Covers `.canon/config.json` load/save, the `has_verification_signal`
precondition's truthy/falsy cases, and one fixture repo per
`suggest_verify_command` branch -- the properties Step 2's plan calls out
as non-negotiable for this module.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _config


class LoadConfigTests(unittest.TestCase):
    def test_returns_none_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_config.load_config(Path(tmp)))

    def test_returns_none_on_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(_config.load_config(root))

    def test_returns_none_on_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertIsNone(_config.load_config(root))

    def test_parses_a_valid_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps({"verify": "just test"}), encoding="utf-8"
            )
            self.assertEqual(_config.load_config(root), {"verify": "just test"})


class SaveConfigTests(unittest.TestCase):
    def test_creates_canon_directory_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _config.save_config(root, {"verify": "pytest"})
            config_path = root / ".canon" / "config.json"
            self.assertTrue(config_path.exists())
            self.assertEqual(_config.load_config(root), {"verify": "pytest"})

    def test_overwrites_an_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _config.save_config(root, {"verify": "pytest"})
            _config.save_config(root, {"verify": "npm test"})
            self.assertEqual(_config.load_config(root), {"verify": "npm test"})


class HasVerificationSignalTests(unittest.TestCase):
    def test_none_config_is_false(self) -> None:
        self.assertFalse(_config.has_verification_signal(None))

    def test_empty_config_is_false(self) -> None:
        self.assertFalse(_config.has_verification_signal({}))

    def test_empty_string_verify_is_false(self) -> None:
        self.assertFalse(_config.has_verification_signal({"verify": ""}))

    def test_whitespace_only_verify_is_false(self) -> None:
        self.assertFalse(_config.has_verification_signal({"verify": "   "}))

    def test_non_string_verify_is_false(self) -> None:
        self.assertFalse(_config.has_verification_signal({"verify": 123}))

    def test_real_command_is_true(self) -> None:
        self.assertTrue(_config.has_verification_signal({"verify": "just test"}))


class SuggestVerifyCommandTests(unittest.TestCase):
    def test_justfile_with_top_level_test_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Justfile").write_text(
                "build:\n    bazel build //...\n\ntest *args:\n    bazel test\n",
                encoding="utf-8",
            )
            self.assertEqual(_config.suggest_verify_command(root), "just test")

    def test_justfile_without_test_recipe_falls_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Justfile").write_text(
                "build:\n    bazel build //...\n", encoding="utf-8"
            )
            self.assertIsNone(_config.suggest_verify_command(root))

    def test_indented_test_line_does_not_count_as_a_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Justfile").write_text(
                "build:\n    test -f foo && bazel build //...\n", encoding="utf-8"
            )
            self.assertIsNone(_config.suggest_verify_command(root))

    def test_pyproject_with_pytest_ini_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8"
            )
            self.assertEqual(_config.suggest_verify_command(root), "pytest")

    def test_pyproject_with_tests_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "x"\n', encoding="utf-8"
            )
            (root / "tests").mkdir()
            self.assertEqual(_config.suggest_verify_command(root), "pytest")

    def test_pyproject_with_neither_signal_falls_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "x"\n', encoding="utf-8"
            )
            self.assertIsNone(_config.suggest_verify_command(root))

    def test_package_json_with_real_test_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8"
            )
            self.assertEqual(_config.suggest_verify_command(root), "npm test")

    def test_package_json_with_placeholder_test_script_falls_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps(
                    {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}
                ),
                encoding="utf-8",
            )
            self.assertIsNone(_config.suggest_verify_command(root))

    def test_notebook_is_last_resort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "analysis.ipynb").write_text("{}", encoding="utf-8")
            self.assertEqual(
                _config.suggest_verify_command(root), "pytest --nbval-lax ."
            )

    def test_notebook_checkpoints_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoints = root / ".ipynb_checkpoints"
            checkpoints.mkdir()
            (checkpoints / "analysis-checkpoint.ipynb").write_text(
                "{}", encoding="utf-8"
            )
            self.assertIsNone(_config.suggest_verify_command(root))

    def test_notebook_is_last_resort_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "analysis.ipynb").write_text("{}", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8"
            )
            self.assertEqual(_config.suggest_verify_command(root), "pytest")

    def test_nothing_matches_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_config.suggest_verify_command(Path(tmp)))


class GuardDefaultBranchTests(unittest.TestCase):
    def test_true_when_no_config(self) -> None:
        self.assertTrue(_config.guard_default_branch(None))

    def test_true_when_key_absent(self) -> None:
        self.assertTrue(_config.guard_default_branch({}))

    def test_false_when_explicitly_opted_out(self) -> None:
        self.assertFalse(_config.guard_default_branch({"guard_default_branch": False}))

    def test_true_when_explicitly_true(self) -> None:
        self.assertTrue(_config.guard_default_branch({"guard_default_branch": True}))


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


class ShellMetacharacterTests(unittest.TestCase):
    """The compound-command detector `verify_command_problem` relies on.

    Covers every character docs/plan.md §07's refusal is built around,
    plus the near miss that a naive substring scan gets wrong: the same
    characters sitting quoted, as ordinary argument content."""

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

    def test_double_quoted_ampersands_are_not_a_metacharacter(self) -> None:
        self.assertIsNone(
            _config.shell_metacharacter('just check --flags="x && y"')
        )

    def test_quoted_backtick_is_not_a_metacharacter(self) -> None:
        self.assertIsNone(_config.shell_metacharacter('echo "`whoami`"'))

    def test_a_wholly_quoted_command_substitution_is_rejected_conservatively(
        self,
    ) -> None:
        """The one deliberate over-rejection: `$(` merges from two
        *different* punctuation characters, so it can't use the
        "every character is an operator character" rule the rest of
        this function relies on to tell operator from content. A token
        that is entirely `"$(...)"`, quoted or not, is treated as
        unsafe rather than trying to also prove it was quoted -- see
        the docstring's `$(` paragraph. No real verify command is
        shaped like this."""
        self.assertEqual(_config.shell_metacharacter('echo "$(whoami)"'), "$(")

    def test_a_prefixed_quoted_command_substitution_is_not_a_metacharacter(
        self,
    ) -> None:
        """The case the conservative rule above does not need to give
        up on: a `$(...)` sitting inside a larger quoted argument fuses
        into a token that does not *start* with `$(`."""
        self.assertIsNone(_config.shell_metacharacter('just check --flags="$(x)"'))

    def test_unterminated_quote_is_not_reported_as_a_metacharacter(self) -> None:
        """A parse failure is a different, separately-handled problem --
        see `verify_command_problem` -- so this returns None rather than
        raising."""
        self.assertIsNone(_config.shell_metacharacter('unterminated "quote'))

    # The blind spots an independent review found in the first version of
    # this function -- reproduced directly against that version before
    # being fixed here, so these pin the fix rather than just the intent.

    def test_stderr_redirect_to_stdout_is_detected(self) -> None:
        """`pytest 2>&1` tokenizes to a merged `>&` token -- not the bare
        `>` the original exact-membership check looked for -- so it was
        silently accepted while the near-identical `pytest 2>/dev/null`
        was correctly rejected. Both must be rejected."""
        self.assertIsNotNone(_config.shell_metacharacter("pytest 2>&1"))

    def test_backgrounding_with_more_after_it_is_detected(self) -> None:
        """A lone `&` was not in the old exact-membership set at all --
        only `&&` was. `ruff check . & pytest` runs `ruff` backgrounded
        with `&` and `pytest` as literal arguments and `pytest` never
        runs; `ruff` alone can exit 0, producing a false green on the one
        gate that must never report one."""
        self.assertIsNotNone(_config.shell_metacharacter("ruff check . & pytest"))

    def test_trailing_backgrounding_is_detected(self) -> None:
        self.assertIsNotNone(_config.shell_metacharacter("pytest &"))

    def test_append_redirect_is_detected(self) -> None:
        """`>>` tokenizes as one merged token, not the bare `>` the old
        check looked for."""
        self.assertIsNotNone(_config.shell_metacharacter("pytest >> log"))

    def test_combined_redirect_is_detected(self) -> None:
        self.assertIsNotNone(_config.shell_metacharacter("pytest &> log"))
        self.assertIsNotNone(_config.shell_metacharacter("pytest 1>&2"))

    def test_operator_after_a_hash_is_still_detected(self) -> None:
        """`shlex.shlex` defaults `commenters` to "#", but `shlex.split`
        -- what actually runs the command -- does not treat `#` as a
        comment at all. Left at the default, this function would stop
        reading at the `#` and miss the `&&` that `shlex.split` still
        hands to the first program as a literal argument."""
        self.assertIsNotNone(
            _config.shell_metacharacter("just test # && ruff check .")
        )

    # Required accepts an independent review pinned explicitly, so a
    # future tightening of the operator rule can't silently break them.

    def test_process_substitution_is_not_rejected(self) -> None:
        """`<(` merges `<` with a `(` -- `(` is deliberately not an
        operator character (see the docstring), so this fails the
        "every character is an operator character" test the same way a
        bare `(` does, and is left alone rather than treated like a
        real `<` redirect."""
        self.assertIsNone(_config.shell_metacharacter("cmd <(foo)"))

    def test_pytest_dash_m_with_parens_is_not_rejected(self) -> None:
        self.assertIsNone(
            _config.shell_metacharacter('pytest -m "not (slow or net)"')
        )

    def test_bazel_test_output_errors_is_not_rejected(self) -> None:
        self.assertIsNone(
            _config.shell_metacharacter("bazel test //... --test_output=errors")
        )


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

    def test_compound_command_suggests_a_wrapper(self) -> None:
        problem = _config.verify_command_problem("ruff check . && pytest")
        assert problem is not None
        self.assertIn("recipe", problem)

    def test_unterminated_quote_is_a_problem(self) -> None:
        problem = _config.verify_command_problem('unterminated "quote')
        self.assertIsNotNone(problem)
        assert problem is not None
        self.assertIn("could not parse", problem)


class VerifyCommandSourceTests(unittest.TestCase):
    """A caller reporting a problem with the resolved command must name
    the file a human should actually go edit -- see
    `stop.py`'s `_handle_configuration_fault` and
    `evidence.py`'s `build_evidence`, both of which name this instead of
    hard-coding `.canon/config.json`."""

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


class ResolveVerifyCommandTests(unittest.TestCase):
    """§07: "`verify:` in a plan header | Overrides it for that branch"."""

    def _repo(self, root: Path, header_verify: str | None) -> None:
        plan = root / ".canon" / "plans" / "feature"
        plan.mkdir(parents=True, exist_ok=True)
        value = f'"{header_verify}"' if header_verify else ""
        (plan / "widget.md").write_text(
            f"---\nstatus: approved\nverify: {value}\n---\n\n## Approach\nx\n",
            encoding="utf-8",
        )

    def test_header_overrides_the_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo(root, "pytest tests/slugs/ -x")
            self.assertEqual(
                _config.resolve_verify_command(
                    root, "feature/widget", {"verify": "just test"}
                ),
                "pytest tests/slugs/ -x",
            )

    def test_blank_header_falls_back_to_the_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo(root, None)
            self.assertEqual(
                _config.resolve_verify_command(
                    root, "feature/widget", {"verify": "just test"}
                ),
                "just test",
            )

    def test_a_config_edit_reaches_a_branch_whose_plan_predates_it(self) -> None:
        """The regression this step exists to prevent. If `save_plan`
        pinned the config value into every header, a later change to
        `.canon/config.json` would be silently ignored here."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo(root, None)  # plan saved under the old config
            self.assertEqual(
                _config.resolve_verify_command(
                    root, "feature/widget", {"verify": "just check"}
                ),
                "just check",
            )

    def test_no_plan_file_falls_back_to_the_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                _config.resolve_verify_command(
                    Path(tmp), "feature/widget", {"verify": "just test"}
                ),
                "just test",
            )

    def test_none_branch_falls_back_to_the_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                _config.resolve_verify_command(Path(tmp), None, {"verify": "x"}),
                "x",
            )

    def test_no_config_and_no_header_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                _config.resolve_verify_command(Path(tmp), "feature/widget", None)
            )

    def test_a_header_override_does_not_activate_an_inert_canon(self) -> None:
        """Whether Canon participates is a repository-level question the
        config alone answers -- a plan header must not switch it on."""
        self.assertFalse(_config.canon_is_active(None))


if __name__ == "__main__":
    unittest.main()
