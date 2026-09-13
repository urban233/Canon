# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_steps.py.

`parse_steps`/`annotate`/`summarize` are pure -- every fact about the
repository arrives as an argument -- so the whole of §06's "which step
am I on" is exercised here without a git repository or a `gh` login.
"""

from __future__ import annotations

import unittest
from typing import Any

from canon_mcp import _steps

_SECTION = """
- slugs: make duplicate slugs raise
- permalinks-api: expose the permalink endpoint
- docs: write the migration note
"""


class ParseStepsTests(unittest.TestCase):
    def test_parses_slug_and_description_in_order(self) -> None:
        steps = _steps.parse_steps(_SECTION)
        self.assertEqual(
            [s["slug"] for s in steps], ["slugs", "permalinks-api", "docs"]
        )
        self.assertEqual([s["index"] for s in steps], [1, 2, 3])
        self.assertEqual(steps[0]["description"], "make duplicate slugs raise")

    def test_accepts_a_numbered_list(self) -> None:
        steps = _steps.parse_steps("1. slugs: do it\n2. docs: write it")
        self.assertEqual([s["slug"] for s in steps], ["slugs", "docs"])

    def test_accepts_a_backticked_slug(self) -> None:
        self.assertEqual(_steps.parse_steps("- `slugs`: do it")[0]["slug"], "slugs")

    def test_keeps_a_line_with_no_slug_but_marks_it_unmatchable(self) -> None:
        """An old feature plan must degrade to "I can't tell", never to a
        confident wrong answer -- and the count must stay honest."""
        steps = _steps.parse_steps("- make duplicate slugs raise\n- docs: write it")
        self.assertEqual(len(steps), 2)
        self.assertIsNone(steps[0]["slug"])
        self.assertEqual(steps[0]["description"], "make duplicate slugs raise")

    def test_ignores_prose_between_entries(self) -> None:
        steps = _steps.parse_steps("Intro prose.\n\n- slugs: do it\n\nMore prose.")
        self.assertEqual(len(steps), 1)

    def test_empty_section_is_no_steps(self) -> None:
        self.assertEqual(_steps.parse_steps(""), [])


class NestedContentTests(unittest.TestCase):
    """Both cases were found by pointing this at Canon's own feature
    plan, which reported 30 steps where there are 9."""

    def test_indented_bullets_are_sub_points_not_steps(self) -> None:
        section = (
            "- slugs: make duplicate slugs raise\n"
            "  - first narrow the regex\n"
            "  - then add the test\n"
            "- docs: write the migration note\n"
        )
        steps = _steps.parse_steps(section)
        self.assertEqual([s["slug"] for s in steps], ["slugs", "docs"])

    def test_a_subsection_heading_ends_the_list(self) -> None:
        """A `## Steps` section carrying per-step detail in `###`
        subsections must not contribute every bullet in that prose."""
        section = (
            "- slugs: make duplicate slugs raise\n"
            "\n### 1 - slugs, in detail\n"
            "- Change the regex\n"
            "- Add a regression test\n"
        )
        steps = _steps.parse_steps(section)
        self.assertEqual([s["slug"] for s in steps], ["slugs"])


class AnnotateTests(unittest.TestCase):
    @property
    def steps(self) -> list[dict[str, Any]]:
        return _steps.parse_steps(_SECTION)

    def test_merged_pull_request_marks_a_step_done(self) -> None:
        annotated = _steps.annotate(
            self.steps,
            branches=set(),
            pulls={"slugs": {"number": 1, "state": "MERGED"}},
            merged_branches=set(),
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_MERGED)

    def test_merged_is_read_from_the_pull_request_not_the_branch(self) -> None:
        """With "automatically delete head branches" on there is no
        branch left to inspect once a step lands."""
        annotated = _steps.annotate(
            self.steps,
            branches=set(),
            pulls={"slugs": {"number": 1, "state": "MERGED"}},
            merged_branches=set(),
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_MERGED)
        self.assertEqual(annotated[0]["pull_request"]["number"], 1)

    def test_a_merged_branch_also_counts(self) -> None:
        annotated = _steps.annotate(
            self.steps,
            branches={"slugs"},
            pulls={},
            merged_branches={"slugs"},
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_MERGED)

    def test_open_pull_request(self) -> None:
        annotated = _steps.annotate(
            self.steps,
            branches={"slugs"},
            pulls={"slugs": {"number": 2, "state": "OPEN"}},
            merged_branches=set(),
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_OPEN)

    def test_branch_without_a_pull_request_is_started(self) -> None:
        annotated = _steps.annotate(
            self.steps, branches={"slugs"}, pulls={}, merged_branches=set()
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_STARTED)

    def test_nothing_at_all_is_not_started(self) -> None:
        annotated = _steps.annotate(
            self.steps, branches=set(), pulls={}, merged_branches=set()
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_NOT_STARTED)

    def test_a_prefixed_branch_matches_its_step(self) -> None:
        annotated = _steps.annotate(
            self.steps, branches={"feature/slugs"}, pulls={}, merged_branches=set()
        )
        self.assertEqual(annotated[0]["branch"], "feature/slugs")
        self.assertEqual(annotated[0]["status"], _steps.STATUS_STARTED)

    def test_a_slugless_step_is_unmatched(self) -> None:
        steps = _steps.parse_steps("- make duplicate slugs raise")
        annotated = _steps.annotate(
            steps, branches={"slugs"}, pulls={}, merged_branches=set()
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_UNMATCHED)
        self.assertIsNone(annotated[0]["branch"])


class DeletedBranchTests(unittest.TestCase):
    """With "automatically delete head branches" enabled there is no
    branch left once a step lands, so the pull request's head ref is the
    only surviving record -- and it carries the branch's prefix.

    Matching pulls by exact slug alone reported every completed step as
    `not started`, which would have left a finished feature reporting as
    stuck on step one forever.
    """

    def test_a_prefixed_pull_request_head_matches_its_step(self) -> None:
        steps = _steps.parse_steps("- 8-notebooks: do the notebooks")
        annotated = _steps.annotate(
            steps,
            branches=set(),
            pulls={"gap/8-notebooks": {"number": 27, "state": "MERGED"}},
            merged_branches=set(),
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_MERGED)
        self.assertEqual(annotated[0]["pull_request"]["number"], 27)
        self.assertEqual(annotated[0]["branch"], "gap/8-notebooks")

    def test_a_prefixed_merged_branch_matches_its_step(self) -> None:
        steps = _steps.parse_steps("- 8-notebooks: do the notebooks")
        annotated = _steps.annotate(
            steps,
            branches={"gap/8-notebooks"},
            pulls={},
            merged_branches={"gap/8-notebooks"},
        )
        self.assertEqual(annotated[0]["status"], _steps.STATUS_MERGED)


class SummarizeTests(unittest.TestCase):
    def _summary(self, pulls: dict[str, dict[str, Any]]) -> dict[str, Any]:
        steps = _steps.annotate(
            _steps.parse_steps(_SECTION),
            branches=set(),
            pulls=pulls,
            merged_branches=set(),
        )
        return _steps.summarize("features/permalinks.md", steps)

    def test_current_is_the_first_unmerged_step(self) -> None:
        summary = self._summary({"slugs": {"state": "MERGED"}})
        self.assertEqual(summary["current"]["index"], 2)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["total"], 3)

    def test_current_is_step_one_when_nothing_has_started(self) -> None:
        summary = self._summary({})
        self.assertEqual(summary["current"]["index"], 1)
        self.assertEqual(summary["completed"], 0)

    def test_current_is_none_when_every_step_landed(self) -> None:
        summary = self._summary(
            {
                "slugs": {"state": "MERGED"},
                "permalinks-api": {"state": "MERGED"},
                "docs": {"state": "MERGED"},
            }
        )
        self.assertIsNone(summary["current"])
        self.assertEqual(summary["completed"], 3)

    def test_an_unmatched_step_never_counts_as_completed(self) -> None:
        steps = _steps.annotate(
            _steps.parse_steps("- no slug here\n- docs: write it"),
            branches=set(),
            pulls={},
            merged_branches=set(),
        )
        summary = _steps.summarize("features/x.md", steps)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(summary["current"]["index"], 1)


if __name__ == "__main__":
    unittest.main()
