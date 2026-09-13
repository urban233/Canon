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


if __name__ == "__main__":
    unittest.main()
