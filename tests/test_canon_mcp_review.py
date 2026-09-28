# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_decisions.py and review.py."""

from __future__ import annotations

import json
import subprocess
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
    """`_reviewers_called_for` now takes the changed paths directly.

    `build_review` resolves the base and the diff once and passes the
    result to both this and the notebook report, rather than each
    recomputing it -- so this is pure and needs no mocking.
    """

    def test_only_reviewer_when_nothing_matches(self) -> None:
        self.assertEqual(review._reviewers_called_for(["README.md"]), ["reviewer"])

    def test_risk_reviewer_joins_on_a_matching_path(self) -> None:
        self.assertEqual(
            review._reviewers_called_for(["migrations/0007.py"]),
            ["reviewer", "risk-reviewer"],
        )

    def test_only_reviewer_when_base_is_unknown(self) -> None:
        """No base means no diff to inspect, which reaches here as None."""
        self.assertEqual(review._reviewers_called_for(None), ["reviewer"])

    def test_only_reviewer_for_an_empty_diff(self) -> None:
        self.assertEqual(review._reviewers_called_for([]), ["reviewer"])


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
            mock.patch("canon_mcp.review.decisions_for", return_value=[]),
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
            mock.patch("canon_mcp.review.decisions_for", return_value=[record]),
        ):
            result = review.build_review(Path("/repo"))
        self.assertFalse(result["stale"])
        self.assertEqual(result["verdict"]["decision"], "READY FOR HUMAN APPROVAL")

    def test_verdict_against_an_older_head_is_stale(self) -> None:
        record = {"decision": "READY FOR HUMAN APPROVAL", "head": "old00000"}
        with (
            mock.patch("canon_mcp.review.head_sha", return_value="new11111"),
            mock.patch("canon_mcp.review.decisions_for", return_value=[record]),
        ):
            result = review.build_review(Path("/repo"))
        self.assertTrue(result["stale"])

    def test_two_reviewers_called_for_but_only_one_verdict_captured(self) -> None:
        def _fake_history(
            root: Path, name: str, branch: str | None = None
        ) -> list[dict[str, Any]]:
            if name == "reviewer":
                return [
                    {
                        "decision": "READY FOR HUMAN APPROVAL",
                        "head": "abc1234d",
                    }
                ]
            return []

        with (
            mock.patch("canon_mcp.review.head_sha", return_value="abc1234d"),
            mock.patch(
                "canon_mcp.review._reviewers_called_for",
                return_value=["reviewer", "risk-reviewer"],
            ),
            mock.patch("canon_mcp.review.decisions_for", side_effect=_fake_history),
        ):
            result = review.build_review(Path("/repo"))
        self.assertEqual(result["reviewers_called_for"], ["reviewer", "risk-reviewer"])
        self.assertIsNone(result["verdict"])
        self.assertIsNone(result["verdicts"]["risk-reviewer"])

    def test_two_reviewers_worst_of_combined(self) -> None:
        def _fake_history(
            root: Path, name: str, branch: str | None = None
        ) -> list[dict[str, Any]]:
            if name == "reviewer":
                return [
                    {
                        "decision": "READY FOR HUMAN APPROVAL",
                        "reason": "looks good",
                        "head": "abc1234d",
                    }
                ]
            return [
                {
                    "decision": "CHANGES REQUIRED",
                    "reason": "fix the backfill window",
                    "head": "abc1234d",
                }
            ]

        with (
            mock.patch("canon_mcp.review.head_sha", return_value="abc1234d"),
            mock.patch(
                "canon_mcp.review._reviewers_called_for",
                return_value=["reviewer", "risk-reviewer"],
            ),
            mock.patch("canon_mcp.review.decisions_for", side_effect=_fake_history),
        ):
            result = review.build_review(Path("/repo"))
        assert result["verdict"] is not None
        self.assertEqual(result["verdict"]["decision"], "CHANGES REQUIRED")
        self.assertFalse(result["stale"])


def _write_log(root: Path, records: list[dict[str, Any]]) -> None:
    log_path = root / ".canon" / "hooks" / "decisions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )


class BranchScopingTests(unittest.TestCase):
    """Regression: records carried no branch, so a branch stacked on a
    reviewed parent step inherited the parent's verdicts as its own --
    observed in the field, where `movie-export` first reported
    `movie-effects`' verdicts at `fd5fe9cf5`."""

    def test_a_record_from_another_branch_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_log(
                root,
                [
                    {"hook": "reviewer", "decision": "A", "branch": "movie-export"},
                    {"hook": "reviewer", "decision": "B", "branch": "movie-effects"},
                ],
            )
            record = _decisions.last_decision(root, "reviewer", "movie-export")
            assert record is not None
            self.assertEqual(record["decision"], "A")
            self.assertIsNone(_decisions.last_decision(root, "reviewer", "other"))

    def test_a_record_without_a_branch_matches_any_branch(self) -> None:
        """A log written before branch scoping keeps answering."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_log(root, [{"hook": "reviewer", "decision": "legacy"}])
            record = _decisions.last_decision(root, "reviewer", "movie-export")
            assert record is not None
            self.assertEqual(record["decision"], "legacy")

    def test_decisions_for_is_oldest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_log(
                root,
                [
                    {"hook": "reviewer", "decision": "first", "branch": "b"},
                    {"hook": "stop.py", "decision": "allow", "branch": "b"},
                    {"hook": "reviewer", "decision": "second", "branch": "b"},
                ],
            )
            self.assertEqual(
                [
                    r["decision"]
                    for r in _decisions.decisions_for(root, "reviewer", "b")
                ],
                ["first", "second"],
            )

    def test_build_review_does_not_report_the_parent_steps_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_log(
                root,
                [
                    {
                        "hook": "reviewer",
                        "decision": "READY FOR HUMAN APPROVAL",
                        "head": "fd5fe9cf5",
                        "branch": "movie-effects",
                    }
                ],
            )
            with (
                mock.patch("canon_mcp.review.head_sha", return_value="3d23ac4e4"),
                mock.patch(
                    "canon_mcp.review.current_branch", return_value="movie-export"
                ),
                mock.patch("canon_mcp.review.merge_base", return_value=None),
            ):
                result = review.build_review(root)
        self.assertIsNone(result["verdict"])
        self.assertIsNone(result["verdicts"]["reviewer"])


class LegacyRecordTests(unittest.TestCase):
    """Records written before they carried a branch are narrowed by
    ancestry: measured on the field repository, leaving them unscoped
    counted 14 rounds for one branch and reported the parent's verdict."""

    def _stacked_repo(self, root: Path) -> tuple[str, str]:
        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()

        def commit(message: str) -> str:
            git(
                "-c",
                "user.email=canon@example.com",
                "-c",
                "user.name=Canon Tests",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                message,
            )
            return git("rev-parse", "HEAD")[:9]

        git("init", "-q")
        git("symbolic-ref", "HEAD", "refs/heads/main")
        commit("init")
        git("switch", "-q", "-c", "a")
        parent_head = commit("step a")
        git("switch", "-q", "-c", "b")
        own_head = commit("step b")
        return parent_head, own_head

    def test_only_records_captured_in_base_to_head_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent_head, own_head = self._stacked_repo(root)
            _write_log(
                root,
                [
                    {
                        "hook": "reviewer",
                        "decision": "CHANGES REQUIRED",
                        "head": "0000000aa",
                    },
                    {
                        "hook": "reviewer",
                        "decision": "CHANGES REQUIRED",
                        "head": parent_head,
                    },
                    {
                        "hook": "reviewer",
                        "decision": "READY FOR HUMAN APPROVAL",
                        "head": parent_head,
                    },
                ],
            )
            result = review.build_review(root)
            self.assertIsNone(result["verdicts"]["reviewer"])
            self.assertEqual(result["rounds"], {"reviewer": 0})

            _write_log(
                root,
                [
                    {
                        "hook": "reviewer",
                        "decision": "READY FOR HUMAN APPROVAL",
                        "head": parent_head,
                    },
                    {
                        "hook": "reviewer",
                        "decision": "CHANGES REQUIRED",
                        "head": own_head,
                    },
                ],
            )
            result = review.build_review(root)
            self.assertEqual(result["verdicts"]["reviewer"]["head"], own_head)
            self.assertEqual(result["rounds"], {"reviewer": 1})


class RoundsTests(unittest.TestCase):
    def test_counts_changes_required_verdicts_on_this_branch_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_log(
                root,
                [
                    {"hook": "reviewer", "decision": "CHANGES REQUIRED", "branch": "a"},
                    {"hook": "reviewer", "decision": "CHANGES REQUIRED", "branch": "b"},
                    {
                        "hook": "reviewer",
                        "decision": "READY FOR HUMAN APPROVAL",
                        "branch": "b",
                    },
                    {"hook": "reviewer", "decision": "CHANGES REQUIRED", "branch": "b"},
                ],
            )
            with (
                mock.patch("canon_mcp.review.head_sha", return_value="abc"),
                mock.patch("canon_mcp.review.current_branch", return_value="b"),
                mock.patch("canon_mcp.review.merge_base", return_value=None),
            ):
                result = review.build_review(root)
        self.assertEqual(result["rounds"], {"reviewer": 2})

    def test_zero_before_any_verdict(self) -> None:
        with (
            mock.patch("canon_mcp.review.head_sha", return_value="abc"),
            mock.patch("canon_mcp.review.decisions_for", return_value=[]),
        ):
            result = review.build_review(Path("/repo"))
        self.assertEqual(result["rounds"], {"reviewer": 0})


def _notebook_json(*sources: str) -> str:
    return json.dumps(
        {
            "cells": [
                {
                    "cell_type": "code",
                    "source": [s],
                    "execution_count": 1,
                    "outputs": [{"text": "noise"}],
                    "metadata": {},
                }
                for s in sources
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )


class NotebookReportTests(unittest.TestCase):
    """\u00a707: hand the reviewer the jupytext `.py` where one exists,
    otherwise the extracted code-cell source -- and tell it which."""

    def _report(
        self, root: Path, before: str | None, after: str | None
    ) -> dict[str, Any]:
        def fake_show(_root: Path, revision: str, _path: str) -> str | None:
            return after if revision == "HEAD" else before

        with mock.patch("canon_mcp.review.file_at_revision", side_effect=fake_show):
            return review._notebook_report(root, "abc1234", "analysis.ipynb")

    def test_extracted_form_carries_source_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._report(
                Path(tmp), _notebook_json("x = 1"), _notebook_json("x = 2")
            )
            self.assertEqual(report["form"], "extracted")
            self.assertIn("x = 2", report["source"])
            self.assertNotIn("noise", report["source"])
            self.assertIn("execution_count", report["note"])
            self.assertEqual(report["code_cells_changed"], 1)

    def test_jupytext_pairing_is_preferred_over_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "analysis.py").write_text("# %%\nx = 2\n", encoding="utf-8")
            report = self._report(
                root, _notebook_json("x = 1"), _notebook_json("x = 2")
            )
            self.assertEqual(report["form"], "jupytext")
            self.assertEqual(report["script_path"], "analysis.py")
            self.assertNotIn("source", report)

    def test_unparsable_notebook_is_reported_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._report(Path(tmp), None, "not a notebook")
            self.assertEqual(report["form"], "unavailable")
            self.assertIsNone(report["code_cells_changed"])

    def test_only_notebooks_are_reported(self) -> None:
        with mock.patch("canon_mcp.review._notebook_report") as reported:
            review._notebooks(Path("/repo"), "abc1234", ["a.py", "b.ipynb"])
        self.assertEqual(reported.call_count, 1)
        self.assertEqual(reported.call_args[0][2], "b.ipynb")

    def test_no_base_means_no_notebook_report(self) -> None:
        self.assertEqual(review._notebooks(Path("/repo"), None, ["b.ipynb"]), [])


if __name__ == "__main__":
    unittest.main()
