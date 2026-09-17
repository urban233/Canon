# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/position.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from canon_mcp import position


def _empty_plan() -> dict[str, Any]:
    return {"header": {}, "sections": {}}


def _no_review() -> dict[str, Any]:
    return {"reviewers_called_for": ["reviewer"], "verdict": None}


def _review(decision: str, *, stale: bool = False, reason: str = "") -> dict[str, Any]:
    return {
        "reviewers_called_for": ["reviewer"],
        "verdict": {"decision": decision, "reason": reason},
        "stale": stale,
    }


class CheckStateTests(unittest.TestCase):
    def test_no_checks_is_all_clear(self) -> None:
        pr: dict[str, Any] = {"statusCheckRollup": []}
        self.assertEqual(position._check_state(pr), (None, None))

    def test_a_failing_check_is_reported_first(self) -> None:
        pr = {
            "statusCheckRollup": [
                {"name": "ci", "conclusion": "FAILURE", "status": "COMPLETED"}
            ]
        }
        self.assertEqual(position._check_state(pr), ("ci", None))

    def test_an_incomplete_check_is_reported(self) -> None:
        pr = {"statusCheckRollup": [{"name": "ci", "status": "IN_PROGRESS"}]}
        self.assertEqual(position._check_state(pr), (None, "ci"))

    def test_a_completed_passing_check_is_clear(self) -> None:
        pr = {
            "statusCheckRollup": [
                {"name": "ci", "conclusion": "SUCCESS", "status": "COMPLETED"}
            ]
        }
        self.assertEqual(position._check_state(pr), (None, None))


class NextStepTests(unittest.TestCase):
    def test_no_verify_signal_wins_first(self) -> None:
        step = position._next_step(False, None, None, _no_review())
        self.assertIn("first-run setup", step)

    def test_no_plan_when_verified(self) -> None:
        step = position._next_step(True, None, None, _no_review())
        self.assertIn("plan mode", step)

    def test_no_pr_when_plan_exists(self) -> None:
        plan = _empty_plan()
        step = position._next_step(True, plan, None, _no_review())
        self.assertIn("open a pull request", step)

    def test_closed_pr_is_reported(self) -> None:
        plan = _empty_plan()
        pr: dict[str, Any] = {"number": 6, "state": "MERGED", "statusCheckRollup": []}
        step = position._next_step(True, plan, pr, _no_review())
        self.assertIn("#6", step)
        self.assertIn("merged", step)

    def test_failing_check_is_named(self) -> None:
        plan = _empty_plan()
        pr = {
            "number": 7,
            "state": "OPEN",
            "statusCheckRollup": [
                {"name": "ci", "conclusion": "FAILURE", "status": "COMPLETED"}
            ],
        }
        step = position._next_step(True, plan, pr, _no_review())
        self.assertIn("fix the failing check (ci)", step)

    def test_incomplete_check_asks_to_wait(self) -> None:
        plan = _empty_plan()
        pr = {
            "number": 7,
            "state": "OPEN",
            "statusCheckRollup": [{"name": "ci", "status": "IN_PROGRESS"}],
        }
        step = position._next_step(True, plan, pr, _no_review())
        self.assertIn("wait for CI", step)

    def test_no_verdict_yet_asks_to_dispatch_the_reviewer(self) -> None:
        plan = _empty_plan()
        pr: dict[str, Any] = {"number": 7, "state": "OPEN", "statusCheckRollup": []}
        step = position._next_step(True, plan, pr, _no_review())
        self.assertIn("dispatch the reviewer", step)

    def test_no_verdict_yet_with_two_reviewers_names_both(self) -> None:
        plan = _empty_plan()
        pr: dict[str, Any] = {"number": 7, "state": "OPEN", "statusCheckRollup": []}
        review: dict[str, Any] = {
            "reviewers_called_for": ["reviewer", "risk-reviewer"],
            "verdict": None,
        }
        step = position._next_step(True, plan, pr, review)
        self.assertIn("dispatch the reviewer and risk-reviewer subagents", step)

    def test_stale_verdict_asks_for_a_delta_re_review(self) -> None:
        """The wording has to agree with the `review` skill, which asks
        for the delta since the commit that reviewer last saw *alongside*
        the full range. "Dispatch again" alone reads as "review it all
        from scratch", which is exactly the re-read that hides a fix
        breaking something already passed."""
        plan = _empty_plan()
        pr: dict[str, Any] = {"number": 7, "state": "OPEN", "statusCheckRollup": []}
        review = _review("READY FOR HUMAN APPROVAL", stale=True)
        step = position._next_step(True, plan, pr, review)
        self.assertIn("re-review", step)
        self.assertIn("delta", step)
        self.assertIn("full range", step)

    def test_changes_required(self) -> None:
        plan = _empty_plan()
        pr: dict[str, Any] = {"number": 7, "state": "OPEN", "statusCheckRollup": []}
        review = _review("CHANGES REQUIRED")
        step = position._next_step(True, plan, pr, review)
        self.assertIn("address the reviewer's requested changes", step)

    def test_blocked_by_missing_evidence(self) -> None:
        plan = _empty_plan()
        pr: dict[str, Any] = {"number": 7, "state": "OPEN", "statusCheckRollup": []}
        review = _review("BLOCKED BY MISSING EVIDENCE", reason="no diff supplied")
        step = position._next_step(True, plan, pr, review)
        self.assertIn("resolve what's blocking review", step)
        self.assertIn("no diff supplied", step)

    def test_ready_for_human_approval_is_ready_to_merge(self) -> None:
        plan = _empty_plan()
        pr: dict[str, Any] = {"number": 7, "state": "OPEN", "statusCheckRollup": []}
        review = _review("READY FOR HUMAN APPROVAL")
        step = position._next_step(True, plan, pr, review)
        self.assertIn("ready for a human to merge", step)


class BuildPositionTests(unittest.TestCase):
    def test_assembles_fields_and_skips_pr_lookup_on_default_branch(self) -> None:
        with (
            mock.patch("canon_mcp.position.current_branch", return_value="main"),
            mock.patch("canon_mcp.position.default_branch", return_value="main"),
            mock.patch("canon_mcp.position.merge_base", return_value="abc1234"),
            mock.patch("canon_mcp.position.head_sha", return_value="def5678"),
            mock.patch("canon_mcp.position.commits_ahead", return_value=0),
            mock.patch("canon_mcp.position.read_plan_file", return_value=None),
            mock.patch("canon_mcp.position.load_config", return_value=None),
            mock.patch("canon_mcp.position.pr_view") as pr_view_mock,
            mock.patch("canon_mcp.position.build_review", return_value=_no_review()),
        ):
            result = position.build_position(Path("/repo"))

        pr_view_mock.assert_not_called()
        self.assertEqual(result["branch"], "main")
        self.assertIsNone(result["pull_request"])
        self.assertFalse(result["verify_configured"])
        self.assertEqual(result["mode"], "solo")
        self.assertIn("first-run setup", result["next_step"])

    def test_looks_up_the_pr_on_a_feature_branch(self) -> None:
        pr: dict[str, Any] = {"number": 7, "state": "OPEN", "statusCheckRollup": []}
        _saved_plan: dict[str, Any] = {
            "header": {"status": "approved", "done": "", "verify": "just test"},
            "sections": {},
        }
        review = _review("READY FOR HUMAN APPROVAL")
        with (
            mock.patch(
                "canon_mcp.position.current_branch", return_value="feature/widget"
            ),
            mock.patch("canon_mcp.position.default_branch", return_value="main"),
            mock.patch("canon_mcp.position.merge_base", return_value="abc1234"),
            mock.patch("canon_mcp.position.head_sha", return_value="def5678"),
            mock.patch("canon_mcp.position.commits_ahead", return_value=3),
            mock.patch(
                "canon_mcp.position.read_plan_file",
                return_value=_saved_plan,
            ),
            mock.patch(
                "canon_mcp.position.load_config", return_value={"verify": "just test"}
            ),
            mock.patch("canon_mcp.position.pr_view", return_value=pr),
            mock.patch("canon_mcp.position.build_review", return_value=review),
        ):
            result = position.build_position(Path("/repo"))

        self.assertEqual(result["pull_request"], pr)
        self.assertEqual(result["review"], review)
        self.assertTrue(result["verify_configured"])
        self.assertEqual(result["plan"]["verify"], "just test")
        self.assertIn("ready for a human to merge", result["next_step"])

    def test_surfaces_a_configured_mode(self) -> None:
        with (
            mock.patch("canon_mcp.position.current_branch", return_value="main"),
            mock.patch("canon_mcp.position.default_branch", return_value="main"),
            mock.patch("canon_mcp.position.merge_base", return_value="abc1234"),
            mock.patch("canon_mcp.position.head_sha", return_value="def5678"),
            mock.patch("canon_mcp.position.commits_ahead", return_value=0),
            mock.patch("canon_mcp.position.read_plan_file", return_value=None),
            mock.patch(
                "canon_mcp.position.load_config", return_value={"mode": "async"}
            ),
            mock.patch("canon_mcp.position.pr_view"),
            mock.patch("canon_mcp.position.build_review", return_value=_no_review()),
        ):
            result = position.build_position(Path("/repo"))
        self.assertEqual(result["mode"], "async")


class FeatureStepTests(unittest.TestCase):
    """§06's "which step am I on?", end to end from a branch plan's
    `parent:` through the feature plan's `## Steps`."""

    def _repo(self, tmp: str, *, parent: str = "permalinks.md") -> Path:
        root = Path(tmp)
        plans = root / ".canon" / "plans"
        (plans / "features").mkdir(parents=True)
        (plans / "features" / "permalinks.md").write_text(
            "---\nstatus: approved\nsteps:\n---\n\n"
            "# Permalinks\n\n## Steps\n"
            "- slugs: make duplicate slugs raise\n"
            "- permalinks-api: expose the endpoint\n"
            "- docs: write the migration note\n",
            encoding="utf-8",
        )
        (plans / "permalinks-api.md").write_text(
            f'---\nstatus: approved\nparent: "features/{parent}"\n---\n\n'
            "## Approach\nx\n",
            encoding="utf-8",
        )
        return root

    def _build(self, root: Path, pulls: dict[str, dict[str, object]]):
        with (
            mock.patch(
                "canon_mcp.position.current_branch", return_value="permalinks-api"
            ),
            mock.patch("canon_mcp.position.default_branch", return_value="main"),
            mock.patch("canon_mcp.position.merge_base", return_value="abc123456"),
            mock.patch("canon_mcp.position.head_sha", return_value="def123456"),
            mock.patch("canon_mcp.position.commits_ahead", return_value=2),
            mock.patch("canon_mcp.position.pr_view", return_value=None),
            mock.patch(
                "canon_mcp.position.build_review", return_value={"verdict": None}
            ),
            mock.patch("canon_mcp.position.load_config", return_value={"verify": "x"}),
            mock.patch(
                "canon_mcp.position.branch_names", return_value={"permalinks-api"}
            ),
            mock.patch("canon_mcp.position.merged_branch_names", return_value=set()),
            mock.patch("canon_mcp.position.pr_list_by_head", return_value=pulls),
        ):
            return position.build_position(root)

    def test_reports_the_current_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            result = self._build(root, {"slugs": {"number": 1, "state": "MERGED"}})
            feature = result["feature"]
            self.assertIsNotNone(feature)
            self.assertEqual(feature["total"], 3)
            self.assertEqual(feature["completed"], 1)
            self.assertEqual(feature["current"]["slug"], "permalinks-api")
            self.assertIn("step 2 of 3", result["summary"])

    def test_a_branch_with_no_parent_has_no_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".canon" / "plans").mkdir(parents=True)
            (root / ".canon" / "plans" / "permalinks-api.md").write_text(
                "---\nstatus: approved\nparent:\n---\n\n## Approach\nx\n",
                encoding="utf-8",
            )
            result = self._build(root, {})
            self.assertIsNone(result["feature"])
            self.assertNotIn("step", result["summary"])

    def test_a_parent_that_resolves_to_nothing_has_no_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, parent="gone.md")
            self.assertIsNone(self._build(root, {})["feature"])


if __name__ == "__main__":
    unittest.main()
