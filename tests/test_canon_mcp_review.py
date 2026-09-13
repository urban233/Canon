# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_decisions.py and review.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
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


class MatchesRiskSurfaceTests(unittest.TestCase):
    def test_auth_keyword(self) -> None:
        self.assertTrue(review._matches_risk_surface("src/auth/login.py"))

    def test_data_keyword(self) -> None:
        self.assertTrue(review._matches_risk_surface("db/migrations/0007_add_col.py"))

    def test_sql_file(self) -> None:
        self.assertTrue(review._matches_risk_surface("scripts/backfill_totals.sql"))

    def test_unrelated_path_does_not_match(self) -> None:
        self.assertFalse(review._matches_risk_surface("docs/README.md"))


class ReviewersCalledForTests(unittest.TestCase):
    def test_only_reviewer_when_nothing_matches(self) -> None:
        with (
            mock.patch("canon_mcp.review.merge_base", return_value="abc1234"),
            mock.patch("canon_mcp.review.default_branch", return_value="main"),
            mock.patch("canon_mcp.review.changed_paths", return_value=["README.md"]),
        ):
            self.assertEqual(review._reviewers_called_for(Path("/repo")), ["reviewer"])

    def test_risk_reviewer_joins_on_a_matching_path(self) -> None:
        with (
            mock.patch("canon_mcp.review.merge_base", return_value="abc1234"),
            mock.patch("canon_mcp.review.default_branch", return_value="main"),
            mock.patch(
                "canon_mcp.review.changed_paths",
                return_value=["migrations/0007.py"],
            ),
        ):
            self.assertEqual(
                review._reviewers_called_for(Path("/repo")),
                ["reviewer", "risk-reviewer"],
            )

    def test_only_reviewer_when_base_is_unknown(self) -> None:
        with (
            mock.patch("canon_mcp.review.merge_base", return_value=None),
            mock.patch("canon_mcp.review.default_branch", return_value="main"),
        ):
            self.assertEqual(review._reviewers_called_for(Path("/repo")), ["reviewer"])


def _verdict(decision: str, *, reason: str = "", stale: bool = False) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "timestamp": "2026-01-01T00:00:00Z",
        "head": "abc1234d",
        "stale": stale,
    }


class CombineTests(unittest.TestCase):
    def test_none_when_any_verdict_is_missing(self) -> None:
        combined, stale = review._combine(
            {"reviewer": _verdict("READY FOR HUMAN APPROVAL"), "risk-reviewer": None}
        )
        self.assertIsNone(combined)
        self.assertFalse(stale)

    def test_single_reviewer_passthrough(self) -> None:
        verdict = _verdict("CHANGES REQUIRED", reason="fix the loop")
        combined, stale = review._combine({"reviewer": verdict})
        assert combined is not None
        self.assertEqual(combined["decision"], "CHANGES REQUIRED")
        self.assertEqual(combined["reason"], "fix the loop")
        self.assertFalse(stale)

    def test_worst_of_two_prefers_changes_required(self) -> None:
        combined, stale = review._combine(
            {
                "reviewer": _verdict("READY FOR HUMAN APPROVAL", reason="looks good"),
                "risk-reviewer": _verdict(
                    "CHANGES REQUIRED", reason="fix the backfill window"
                ),
            }
        )
        assert combined is not None
        self.assertEqual(combined["decision"], "CHANGES REQUIRED")
        self.assertIn("reviewer: looks good", combined["reason"])
        self.assertIn("risk-reviewer: fix the backfill window", combined["reason"])

    def test_stale_if_any_present_verdict_is_stale(self) -> None:
        combined, stale = review._combine(
            {
                "reviewer": _verdict("READY FOR HUMAN APPROVAL"),
                "risk-reviewer": _verdict("READY FOR HUMAN APPROVAL", stale=True),
            }
        )
        self.assertTrue(stale)


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

    def test_two_reviewers_called_for_but_only_one_verdict_captured(self) -> None:
        def _fake_last_decision(root: Path, name: str) -> dict[str, Any] | None:
            if name == "reviewer":
                return {
                    "decision": "READY FOR HUMAN APPROVAL",
                    "head": "abc1234d",
                }
            return None

        with (
            mock.patch("canon_mcp.review.head_sha", return_value="abc1234d"),
            mock.patch(
                "canon_mcp.review._reviewers_called_for",
                return_value=["reviewer", "risk-reviewer"],
            ),
            mock.patch(
                "canon_mcp.review.last_decision", side_effect=_fake_last_decision
            ),
        ):
            result = review.build_review(Path("/repo"))
        self.assertEqual(result["reviewers_called_for"], ["reviewer", "risk-reviewer"])
        self.assertIsNone(result["verdict"])
        self.assertIsNone(result["verdicts"]["risk-reviewer"])

    def test_two_reviewers_worst_of_combined(self) -> None:
        def _fake_last_decision(root: Path, name: str) -> dict[str, Any] | None:
            if name == "reviewer":
                return {
                    "decision": "READY FOR HUMAN APPROVAL",
                    "reason": "looks good",
                    "head": "abc1234d",
                }
            return {
                "decision": "CHANGES REQUIRED",
                "reason": "fix the backfill window",
                "head": "abc1234d",
            }

        with (
            mock.patch("canon_mcp.review.head_sha", return_value="abc1234d"),
            mock.patch(
                "canon_mcp.review._reviewers_called_for",
                return_value=["reviewer", "risk-reviewer"],
            ),
            mock.patch(
                "canon_mcp.review.last_decision", side_effect=_fake_last_decision
            ),
        ):
            result = review.build_review(Path("/repo"))
        assert result["verdict"] is not None
        self.assertEqual(result["verdict"]["decision"], "CHANGES REQUIRED")
        self.assertFalse(result["stale"])


if __name__ == "__main__":
    unittest.main()
