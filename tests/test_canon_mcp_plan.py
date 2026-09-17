# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_plan.py and plan.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from canon_mcp import _plan, plan

_SAVED_PLAN = """---
status: approved
base: "a41f0c9"
scope:
done: "duplicate slugs raise, with a regression test"
verify: "just test"
parent:
---

## Approach
Do it.

## Non-goals
- Not that.

## Verification
1. Run tests.
"""


class PlanSectionsTests(unittest.TestCase):
    def test_splits_headings_case_and_whitespace_insensitively(self) -> None:
        body = "## Approach\nDo it.\n\n## Non-goals\n- Not that.\n"
        sections = _plan.plan_sections(body)
        self.assertEqual(sections["approach"], "Do it.")
        self.assertEqual(sections["non-goals"], "- Not that.")

    def test_no_headings_yields_empty_dict(self) -> None:
        self.assertEqual(_plan.plan_sections("just prose, no headings"), {})


class ParseHeaderTests(unittest.TestCase):
    def test_quoted_values_are_unescaped(self) -> None:
        header = _plan._parse_header('base: "a41f0c9"\nverify: "just test"\n')
        self.assertEqual(header["base"], "a41f0c9")
        self.assertEqual(header["verify"], "just test")

    def test_bare_keys_are_empty_strings(self) -> None:
        header = _plan._parse_header("scope:\nparent:\n")
        self.assertEqual(header["scope"], "")
        self.assertEqual(header["parent"], "")

    def test_escaped_quotes_and_backslashes_round_trip(self) -> None:
        header = _plan._parse_header(r'notes: "a \"quoted\" word and a \\ backslash"')
        self.assertEqual(header["notes"], 'a "quoted" word and a \\ backslash')


class ReadPlanFileTests(unittest.TestCase):
    def test_returns_none_when_the_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                _plan.read_plan_file(Path(tmp), ".canon/plans/missing.md")
            )

    def test_parses_header_and_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".canon" / "plans" / "fix-slug-collision.md"
            path.parent.mkdir(parents=True)
            path.write_text(_SAVED_PLAN, encoding="utf-8")

            result = _plan.read_plan_file(root, ".canon/plans/fix-slug-collision.md")

            assert result is not None
            self.assertEqual(result["header"]["status"], "approved")
            self.assertEqual(result["header"]["base"], "a41f0c9")
            self.assertEqual(result["header"]["verify"], "just test")
            self.assertEqual(result["sections"]["approach"], "Do it.")
            self.assertEqual(result["sections"]["verification"], "1. Run tests.")

    def test_headerless_file_is_still_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "notes.md"
            path.write_text("## Approach\nHand-written, no header.\n", encoding="utf-8")

            result = _plan.read_plan_file(root, "notes.md")

            assert result is not None
            self.assertEqual(result["header"], {})
            self.assertEqual(result["sections"]["approach"], "Hand-written, no header.")


class BuildPlanTests(unittest.TestCase):
    def test_reads_the_redirected_branch_plan_not_a_same_slug_feature_plan(
        self,
    ) -> None:
        """`_plan.branch_plan_relative` redirects a `features/<x>`
        branch's own plan to `.canon/plans/branches/features/<x>.md`, out
        of the `.canon/plans/features/` namespace a feature plan of that
        slug already occupies. `build_plan` must resolve through that
        redirect -- resolving the plain `.canon/plans/<branch>.md`
        formula instead means `canon_plan` shows the feature plan's body
        as though it were this branch's own."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans = root / ".canon" / "plans"
            (plans / "features").mkdir(parents=True)
            (plans / "features" / "widget.md").write_text(
                "---\nstatus: approved\nsteps:\n---\n\n## Steps\n- a: x\n",
                encoding="utf-8",
            )
            (plans / "branches" / "features").mkdir(parents=True)
            (plans / "branches" / "features" / "widget.md").write_text(
                "---\nstatus: approved\n---\n\n## Approach\nThe branch's own plan.\n",
                encoding="utf-8",
            )

            completed = mock.Mock(returncode=0, stdout="features/widget\n")
            with mock.patch("subprocess.run", return_value=completed):
                result = plan.build_plan(root)

        assert result["plan"] is not None
        self.assertEqual(
            result["plan"]["sections"].get("approach"), "The branch's own plan."
        )

    def test_reports_no_plan_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = mock.Mock(returncode=0, stdout="fix-slug-collision\n")
            with mock.patch("subprocess.run", return_value=completed):
                result = plan.build_plan(Path(tmp))
        self.assertIsNone(result["plan"])
        self.assertIn("no plan saved", result["message"])

    def test_reads_the_current_branch_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".canon" / "plans" / "fix-slug-collision.md"
            path.parent.mkdir(parents=True)
            path.write_text(_SAVED_PLAN, encoding="utf-8")

            completed = mock.Mock(returncode=0, stdout="fix-slug-collision\n")
            with mock.patch("subprocess.run", return_value=completed):
                result = plan.build_plan(root)

        assert result["plan"] is not None
        self.assertEqual(result["plan"]["header"]["status"], "approved")
        self.assertIsNone(result["parent_plan"])

    def test_resolves_one_level_of_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans_dir = root / ".canon" / "plans"
            plans_dir.mkdir(parents=True)
            (plans_dir / "features").mkdir()
            (plans_dir / "public-permalinks.md").write_text(
                "---\nstatus: approved\n---\n\n## Approach\nFeature-level.\n",
                encoding="utf-8",
            )
            step_header = (
                "---\nstatus: approved\n"
                'parent: ".canon/plans/public-permalinks.md"\n---'
            )
            (plans_dir / "step-2.md").write_text(
                step_header + "\n\n## Approach\nStep-level.\n",
                encoding="utf-8",
            )

            completed = mock.Mock(returncode=0, stdout="step-2\n")
            with mock.patch("subprocess.run", return_value=completed):
                result = plan.build_plan(root)

        assert result["parent_plan"] is not None
        self.assertEqual(
            result["parent_plan"]["sections"]["approach"], "Feature-level."
        )


if __name__ == "__main__":
    unittest.main()
