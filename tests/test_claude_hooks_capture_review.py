# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/capture_review.py.

Covers the payload schema confirmed against Claude Code's own hooks
reference (`agent_type`, `last_assistant_message`) rather than the
transcript-file mechanism this hook deliberately does not use, plus the
tolerant agent_type check mirroring save_plan.py's style.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import capture_review

_READY = "READY FOR HUMAN APPROVAL"
_CHANGES = "CHANGES REQUIRED"
_BLOCKED = "BLOCKED BY MISSING EVIDENCE"


class ExtractDecisionTests(unittest.TestCase):
    def test_finds_the_ready_decision(self) -> None:
        message = f"Findings: none.\n\n{_READY}"
        self.assertEqual(capture_review._extract_decision(message), _READY)

    def test_finds_the_changes_required_decision(self) -> None:
        message = f"One blocking finding.\n\n{_CHANGES}"
        self.assertEqual(capture_review._extract_decision(message), _CHANGES)

    def test_returns_none_when_nothing_matches(self) -> None:
        self.assertIsNone(capture_review._extract_decision("still reviewing"))

    def test_last_occurrence_wins_when_more_than_one_appears(self) -> None:
        message = f"Considered {_CHANGES} but concluded {_READY}"
        self.assertEqual(capture_review._extract_decision(message), _READY)


def _invoke_main(payload: dict[str, object]) -> None:
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            capture_review.main()


class MainTests(unittest.TestCase):
    def test_captures_a_verdict_from_the_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = mock.Mock(returncode=0, stdout="abc1234def\n")
            with mock.patch("subprocess.run", return_value=completed):
                _invoke_main(
                    {
                        "cwd": str(root),
                        "agent_type": "reviewer",
                        "last_assistant_message": f"All clear.\n\n{_READY}",
                    }
                )

            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            self.assertTrue(log_path.exists())
            record = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["hook"], "reviewer")
            self.assertEqual(record["decision"], _READY)
            self.assertEqual(record["head"], "abc1234de")
            self.assertIn("All clear.", record["reason"])

    def test_noop_when_agent_type_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _invoke_main(
                {
                    "cwd": str(root),
                    "agent_type": "Explore",
                    "last_assistant_message": _READY,
                }
            )
            self.assertFalse((root / ".canon").exists())

    def test_noop_when_no_decision_string_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _invoke_main(
                {
                    "cwd": str(root),
                    "agent_type": "reviewer",
                    "last_assistant_message": "still thinking it over",
                }
            )
            self.assertFalse((root / ".canon").exists())

    def test_noop_when_last_assistant_message_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _invoke_main({"cwd": str(root), "agent_type": "reviewer"})
            self.assertFalse((root / ".canon").exists())

    def test_reason_is_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_message = ("x" * 500) + f"\n\n{_BLOCKED}"
            completed = mock.Mock(returncode=0, stdout="abc1234def\n")
            with mock.patch("subprocess.run", return_value=completed):
                _invoke_main(
                    {
                        "cwd": str(root),
                        "agent_type": "reviewer",
                        "last_assistant_message": long_message,
                    }
                )

            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            record = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(
                len(record["reason"]), capture_review._REASON_PREVIEW_CHARS
            )


if __name__ == "__main__":
    unittest.main()
