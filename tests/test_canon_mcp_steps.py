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


def _summarize(
    section: str,
    branches: set[str] | None = None,
    pulls: dict[str, dict[str, Any]] | None = None,
    merged: set[str] | None = None,
) -> dict[str, Any]:
    return _steps.summarize(
        "features/x.md",
        _steps.annotate(
            _steps.parse_steps(section),
            branches=branches or set(),
            pulls=pulls or {},
            merged_branches=merged or set(),
        ),
    )


def _startable(summary: dict[str, Any]) -> list[str]:
    return [step["slug"] for step in summary["startable"]]


class DependencyParsingTests(unittest.TestCase):
    def test_a_step_without_an_annotation_waits_for_the_one_before_it(self) -> None:
        steps = _steps.parse_steps("- a: one\n- b: two\n- c: three")
        self.assertEqual([step["depends_on"] for step in steps], [[], ["a"], ["b"]])

    def test_after_none_declares_a_step_that_waits_for_nothing(self) -> None:
        steps = _steps.parse_steps("- a: one\n- b (after: none): two")
        self.assertEqual(steps[1]["depends_on"], [])

    def test_several_dependencies_are_comma_separated(self) -> None:
        steps = _steps.parse_steps("- a: one\n- b: two\n- c (after: a, b): three")
        self.assertEqual(steps[2]["depends_on"], ["a", "b"])

    def test_backticks_and_spacing_around_a_dependency_are_tolerated(self) -> None:
        steps = _steps.parse_steps("- a: one\n- b (after:  `a` ): two")
        self.assertEqual(steps[1]["depends_on"], ["a"])

    def test_after_is_recognised_whatever_its_case(self) -> None:
        steps = _steps.parse_steps("- a: one\n- b (After: a): two")
        self.assertEqual(steps[1]["depends_on"], ["a"])
        self.assertEqual(steps[1]["description"], "two")

    def test_the_annotation_is_kept_out_of_the_description(self) -> None:
        steps = _steps.parse_steps("- a (after: none): expose cmd.* to an agent")
        self.assertEqual(steps[0]["description"], "expose cmd.* to an agent")

    def test_a_parenthesis_that_is_not_an_after_clause_stays_unmatched(self) -> None:
        """Unchanged from before the notation existed: this line never
        parsed as a slug, and must not start now."""
        steps = _steps.parse_steps("- a (the hard one): one")
        self.assertIsNone(steps[0]["slug"])

    def test_a_slugless_step_contributes_no_implicit_dependency(self) -> None:
        steps = _steps.parse_steps("- a: one\n- no slug here\n- c: three")
        self.assertEqual(steps[2]["depends_on"], [])


class StartableTests(unittest.TestCase):
    def test_a_plain_chain_offers_only_its_first_step(self) -> None:
        """The pre-notation meaning, preserved exactly: every plan
        already in a repository stays strictly sequential."""
        summary = _summarize("- a: one\n- b: two\n- c: three")
        self.assertEqual(_startable(summary), ["a"])

    def test_independent_steps_are_all_startable_at_once(self) -> None:
        summary = _summarize("- a: one\n- b (after: none): two")
        self.assertEqual(_startable(summary), ["a", "b"])

    def test_a_join_waits_for_every_dependency(self) -> None:
        section = "- a: one\n- b (after: none): two\n- c (after: a, b): three"
        summary = _summarize(section, branches={"a"}, merged={"a"})
        self.assertEqual(_startable(summary), ["b"])
        self.assertEqual(summary["steps"][2]["blocked_by"], ["b"])

    def test_a_join_becomes_startable_once_all_of_them_merge(self) -> None:
        section = "- a: one\n- b (after: none): two\n- c (after: a, b): three"
        summary = _summarize(section, branches={"a", "b"}, merged={"a", "b"})
        self.assertEqual(_startable(summary), ["c"])

    def test_a_step_already_begun_is_not_offered_again(self) -> None:
        summary = _summarize("- a: one\n- b (after: none): two", branches={"b"})
        self.assertEqual(_startable(summary), ["a"])

    def test_current_keeps_its_meaning_alongside_startable(self) -> None:
        section = "- a: one\n- b (after: none): two\n- c (after: a, b): three"
        summary = _summarize(section, branches={"a"}, merged={"a"})
        self.assertEqual(summary["current"]["slug"], "b")
        self.assertEqual(summary["completed"], 1)

    def test_an_unknown_dependency_blocks_rather_than_being_ignored(self) -> None:
        summary = _summarize("- a: one\n- b (after: ghost): two")
        self.assertEqual(summary["steps"][1]["unknown_dependencies"], ["ghost"])
        self.assertEqual(_startable(summary), ["a"])

    def test_an_unmatched_step_is_never_startable(self) -> None:
        summary = _summarize("- no slug here\n- b (after: none): two")
        self.assertEqual(_startable(summary), ["b"])


class CycleTests(unittest.TestCase):
    def test_no_cycle_in_an_ordinary_plan(self) -> None:
        self.assertEqual(_summarize("- a: one\n- b: two")["cycle"], [])

    def test_two_steps_waiting_on_each_other_are_reported(self) -> None:
        summary = _summarize("- a (after: b): one\n- b (after: a): two")
        self.assertEqual(summary["cycle"], ["a", "b"])
        self.assertEqual(_startable(summary), [])

    def test_a_step_waiting_on_itself_is_reported(self) -> None:
        self.assertEqual(_summarize("- a (after: a): one")["cycle"], ["a"])

    def test_an_unknown_dependency_is_not_a_cycle(self) -> None:
        self.assertEqual(_summarize("- a (after: ghost): one")["cycle"], [])


class RealFeaturePlanTests(unittest.TestCase):
    """The ten-branch stack from `phase-0-2-gap-closure.md`, which had to
    be drawn as an ASCII diagram in prose because `## Steps` could not
    express it. Transcribed here, it must give that diagram's answer."""

    _STACK = "\n".join(
        f"- {index}-step (after: {index - 1}-step): step {index}"
        if index > 1
        else f"- {index}-step (after: none): step {index}"
        for index in range(1, 11)
    )

    def test_a_stack_offers_exactly_one_step_at_a_time(self) -> None:
        summary = _summarize(self._STACK)
        self.assertEqual(_startable(summary), ["1-step"])

    def test_a_stack_advances_one_step_per_merge(self) -> None:
        summary = _summarize(self._STACK, branches={"1-step"}, merged={"1-step"})
        self.assertEqual(_startable(summary), ["2-step"])

    def test_a_fully_landed_stack_offers_nothing(self) -> None:
        landed = {f"{index}-step" for index in range(1, 11)}
        summary = _summarize(self._STACK, branches=landed, merged=landed)
        self.assertEqual(_startable(summary), [])
        self.assertIsNone(summary["current"])


if __name__ == "__main__":
    unittest.main()
