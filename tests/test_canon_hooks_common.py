# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_hooks/_common.py's two generalizations made for
the Codex port: `edited_paths`'s defensive multi-key extraction, and
`state_dir`'s `session_id`-derived fallback for a platform whose payload
carries no `scratchpad_dir`.

Everything else in this module is exercised already by
tests/test_claude_hooks_common.py (via the byte-identical vendored copy
at plugins/claude/hooks/_common.py) -- these tests cover only the
behavior that has no Claude Code counterpart to exercise it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _common


class EditedPathsTests(unittest.TestCase):
    def test_none_payload_yields_no_paths(self) -> None:
        self.assertEqual(_common.edited_paths(None), [])

    def test_missing_tool_input_yields_no_paths(self) -> None:
        self.assertEqual(_common.edited_paths({}), [])

    def test_file_path_key_is_the_first_choice(self) -> None:
        payload = {"tool_input": {"file_path": "src/a.py", "path": "src/b.py"}}
        self.assertEqual(_common.edited_paths(payload), ["src/a.py"])

    def test_path_key_is_used_when_file_path_is_absent(self) -> None:
        payload = {"tool_input": {"path": "src/b.py"}}
        self.assertEqual(_common.edited_paths(payload), ["src/b.py"])

    def test_changes_list_is_used_when_no_single_path_key_is_present(self) -> None:
        payload = {
            "tool_input": {
                "changes": [
                    {"path": "src/a.py", "kind": "add"},
                    {"path": "src/b.py", "kind": "modify"},
                ]
            }
        }
        self.assertEqual(_common.edited_paths(payload), ["src/a.py", "src/b.py"])

    def test_changes_entries_without_a_path_are_skipped(self) -> None:
        payload = {
            "tool_input": {
                "changes": [{"path": "src/a.py"}, {"kind": "add"}, "not-a-dict"]
            }
        }
        self.assertEqual(_common.edited_paths(payload), ["src/a.py"])

    def test_nothing_extractable_yields_an_empty_list_not_an_error(self) -> None:
        payload = {"tool_input": {"command": "echo hi"}}
        self.assertEqual(_common.edited_paths(payload), [])


class StateDirTests(unittest.TestCase):
    def test_scratchpad_dir_is_the_first_choice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"scratchpad_dir": tmp, "session_id": "abc123"}
            result = _common.state_dir(payload)
            self.assertEqual(result, Path(tmp) / "canon")

    def test_session_id_derives_a_directory_when_no_scratchpad_dir_exists(
        self,
    ) -> None:
        """Codex's own payload carries no `scratchpad_dir` (confirmed
        directly -- see docs/codex-hook-surface.md), so this fallback is
        what makes `stop.py`'s and `check_scope.py`'s session-scoped
        counters work there at all."""
        payload = {"session_id": "codex-session-xyz"}
        result = _common.state_dir(payload)
        self.assertIsNotNone(result)
        assert result is not None  # for the type checker
        self.assertEqual(result.name, "canon")
        self.assertEqual(result.parent.name, "codex-session-xyz")
        self.assertEqual(result.parent.parent.name, "canon-hooks")

    def test_different_session_ids_derive_different_directories(self) -> None:
        first = _common.state_dir({"session_id": "session-one"})
        second = _common.state_dir({"session_id": "session-two"})
        self.assertNotEqual(first, second)

    def test_neither_source_present_yields_none(self) -> None:
        self.assertIsNone(_common.state_dir({}))
        self.assertIsNone(_common.state_dir(None))

    def test_a_custom_subdir_is_respected_in_both_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scratchpad_result = _common.state_dir({"scratchpad_dir": tmp}, "widget")
            self.assertEqual(scratchpad_result, Path(tmp) / "widget")
        derived_result = _common.state_dir({"session_id": "s1"}, "widget")
        assert derived_result is not None
        self.assertEqual(derived_result.name, "widget")


if __name__ == "__main__":
    unittest.main()
