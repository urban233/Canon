# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/ship.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from canon_mcp import ship

_APPROVED_PLAN = {"path": ".canon/plans/x.md", "header": {"status": "approved"}}


class PlanReadinessTests(unittest.TestCase):
    def test_no_plan(self) -> None:
        ok, reason = ship._plan_readiness(None)
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("no plan saved", reason)

    def test_plan_with_missing_sections_note(self) -> None:
        """Still a block, not a warning -- see
        docs/decisions/0002-ship-blocks-on-a-missing-required-section.md."""
        plan = {
            "path": ".canon/plans/feature/widget.md",
            "header": {
                "status": "approved",
                "notes": "Non-goals section is missing or empty",
            },
        }
        ok, reason = ship._plan_readiness(plan)
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn(".canon/plans/feature/widget.md", reason)

    def test_missing_sections_note_without_a_path_still_reports(self) -> None:
        """`_plan_readiness` must not KeyError on a plan dict that
        carries no `path` -- it would crash the whole tool."""
        plan = {"header": {"status": "approved", "notes": "Non-goals missing"}}
        ok, reason = ship._plan_readiness(plan)
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("Non-goals missing", reason)
        assert reason is not None
        self.assertIn("missing required sections", reason)

    def test_plan_with_non_approved_status(self) -> None:
        plan = {"header": {"status": "superseded"}}
        ok, reason = ship._plan_readiness(plan)
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("superseded", reason)

    def test_approved_plan_with_no_notes_is_satisfied(self) -> None:
        ok, reason = ship._plan_readiness(_APPROVED_PLAN)
        self.assertTrue(ok)
        self.assertIsNone(reason)


class EvidenceReasonTests(unittest.TestCase):
    def test_unknown_evidence(self) -> None:
        reason = ship._evidence_reason({"green": None, "message": "not pushed"})
        self.assertIn("not pushed", reason)

    def test_red_evidence(self) -> None:
        reason = ship._evidence_reason({"green": False, "detail": "mypy failed"})
        self.assertIn("mypy failed", reason)


class ReviewReadinessTests(unittest.TestCase):
    def test_no_verdict(self) -> None:
        ok, reason = ship._review_readiness({"verdict": None})
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("no reviewer verdict", reason)

    def test_stale_verdict(self) -> None:
        ok, reason = ship._review_readiness(
            {"verdict": {"decision": "READY FOR HUMAN APPROVAL"}, "stale": True}
        )
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("stale", reason)

    def test_changes_required(self) -> None:
        ok, reason = ship._review_readiness(
            {
                "verdict": {"decision": "CHANGES REQUIRED", "reason": "fix the loop"},
                "stale": False,
            }
        )
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("fix the loop", reason)

    def test_blocked_by_missing_evidence(self) -> None:
        ok, reason = ship._review_readiness(
            {
                "verdict": {
                    "decision": "BLOCKED BY MISSING EVIDENCE",
                    "reason": "no diff supplied",
                },
                "stale": False,
            }
        )
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("no diff supplied", reason)

    def test_ready(self) -> None:
        ok, reason = ship._review_readiness(
            {"verdict": {"decision": "READY FOR HUMAN APPROVAL"}, "stale": False}
        )
        self.assertTrue(ok)
        self.assertIsNone(reason)


class BuildShipTests(unittest.TestCase):
    def test_plan_invariant_is_unsatisfied_with_only_a_same_slug_feature_plan(
        self,
    ) -> None:
        """`_plan.branch_plan_relative` redirects a `features/<x>`
        branch's own plan to `.canon/plans/branches/features/<x>.md`, out
        of the `.canon/plans/features/` namespace a feature plan of that
        slug already occupies. `build_ship` must resolve through that
        redirect -- resolving the plain `.canon/plans/<branch>.md`
        formula instead means `canon_ship` reads the feature plan's own
        `status: approved` header and reports the plan invariant
        satisfied on the strength of the wrong file, on the one call that
        decides whether a human should look at the branch. Deliberately
        not mocking `read_plan_file` here, unlike the other tests in this
        class: the real path resolution is exactly what is under test."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature_plan = root / ".canon" / "plans" / "features" / "widget.md"
            feature_plan.parent.mkdir(parents=True)
            feature_plan.write_text(
                "---\nstatus: approved\nsteps:\n---\n\n## Steps\n- a: x\n",
                encoding="utf-8",
            )
            with (
                mock.patch(
                    "canon_mcp.ship.current_branch", return_value="features/widget"
                ),
                mock.patch(
                    "canon_mcp.ship.build_evidence", return_value={"green": True}
                ),
                mock.patch(
                    "canon_mcp.ship.build_review",
                    return_value={
                        "verdict": {"decision": "READY FOR HUMAN APPROVAL"},
                        "stale": False,
                    },
                ),
            ):
                result = ship.build_ship(root)
        self.assertFalse(result["plan"]["satisfied"])
        assert result["plan"]["reason"] is not None
        self.assertIn("no plan saved", result["plan"]["reason"])

    def test_ready_when_all_three_invariants_are_met(self) -> None:
        with (
            mock.patch("canon_mcp.ship.current_branch", return_value="feature/x"),
            mock.patch("canon_mcp.ship.read_plan_file", return_value=_APPROVED_PLAN),
            mock.patch("canon_mcp.ship.build_evidence", return_value={"green": True}),
            mock.patch(
                "canon_mcp.ship.build_review",
                return_value={
                    "verdict": {"decision": "READY FOR HUMAN APPROVAL"},
                    "stale": False,
                },
            ),
        ):
            result = ship.build_ship(Path("/repo"))
        self.assertTrue(result["ready"])
        self.assertEqual(result["missing"], [])

    def test_not_ready_lists_every_unmet_invariant(self) -> None:
        with (
            mock.patch("canon_mcp.ship.current_branch", return_value="feature/x"),
            mock.patch("canon_mcp.ship.read_plan_file", return_value=None),
            mock.patch(
                "canon_mcp.ship.build_evidence",
                return_value={"green": False, "detail": "tests failed"},
            ),
            mock.patch("canon_mcp.ship.build_review", return_value={"verdict": None}),
        ):
            result = ship.build_ship(Path("/repo"))
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["missing"]), 3)


if __name__ == "__main__":
    unittest.main()
