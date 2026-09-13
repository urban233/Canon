# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_decisions.py and review.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from canon_mcp import _decisions, review


class LastDecisionTests(unittest.TestCase):
    def test_returns_none_when_the_log_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_decisions.last_decision(Path(tmp), "reviewer"))

    def test_returns_the_most_recent_matching_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            log_path.parent.mkdir(parents=True)
            lines = [
                {"hook": "reviewer", "decision": "CHANGES REQUIRED"},
                {"hook": "stop.py", "decision": "block"},
                {"hook": "reviewer", "decision": "READY FOR HUMAN APPROVAL"},
            ]
            log_path.write_text(
                "\n".join(json.dumps(line) for line in lines) + "\n",
                encoding="utf-8",
            )
            record = _decisions.last_decision(root, "reviewer")
            assert record is not None
            self.assertEqual(record["decision"], "READY FOR HUMAN APPROVAL")

    def test_ignores_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            log_path.parent.mkdir(parents=True)
            log_path.write_text("not json\n", encoding="utf-8")
            self.assertIsNone(_decisions.last_decision(root, "reviewer"))


class BuildReviewTests(unittest.TestCase):
    def test_no_verdict_captured_yet(self) -> None:
        with (
            mock.patch("canon_mcp.review.head_sha", return_value="abc1234d"),
            mock.patch("canon_mcp.review.last_decision", return_value=None),
        ):
            result = review.build_review(Path("/repo"))
        self.assertEqual(result["reviewers_called_for"], ["reviewer"])
        self.assertIsNone(result["verdict"])

    def test_verdict_matches_current_head_is_not_stale(self) -> None:
        record = {
            "decision": "READY FOR HUMAN APPROVAL",
            "reason": "looks good",
            "timestamp": "2026-01-01T00:00:00Z",
            "head": "abc1234d",
        }
        with (
            mock.patch("canon_mcp.review.head_sha", return_value="abc1234d"),
            mock.patch("canon_mcp.review.last_decision", return_value=record),
        ):
            result = review.build_review(Path("/repo"))
        self.assertFalse(result["stale"])
        self.assertEqual(result["verdict"]["decision"], "READY FOR HUMAN APPROVAL")

    def test_verdict_against_an_older_head_is_stale(self) -> None:
        record = {"decision": "READY FOR HUMAN APPROVAL", "head": "old00000"}
        with (
            mock.patch("canon_mcp.review.head_sha", return_value="new11111"),
            mock.patch("canon_mcp.review.last_decision", return_value=record),
        ):
            result = review.build_review(Path("/repo"))
        self.assertTrue(result["stale"])


if __name__ == "__main__":
    unittest.main()
