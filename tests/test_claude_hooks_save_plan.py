# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/save_plan.py.

Covers reading the approved plan (preferring the on-disk file over the
embedded copy), the derived header (`status`, `base`, `verify` filled in;
`scope`/`done`/`parent` left blank), the missing-required-section notes,
and the silent no-op on anything that isn't an approval -- the properties
Step 4's plan calls out as non-negotiable for this hook.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import save_plan

PLAN_WITH_SECTIONS = """# A title

## Approach
Do the thing.

## Non-goals
- Not doing the other thing.

## Verification
1. Run the tests.
"""

PLAN_MISSING_NON_GOALS = """# A title

## Approach
Do the thing.

## Verification
1. Run the tests.
"""

PLAN_EMPTY_VERIFICATION = """# A title

## Non-goals
- Not doing the other thing.

## Verification

## Risks
None.
"""


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _init_repo(root: Path, branch: str) -> None:
    _run_git(root, "init", "-q")
    _run_git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _run_git(
        root,
        "-c",
        "user.email=canon@example.com",
        "-c",
        "user.name=Canon Tests",
        "commit",
        "--allow-empty",
        "-m",
        "init",
    )
    if branch != "main":
        _run_git(root, "checkout", "-q", "-b", branch)
        _run_git(
            root,
            "-c",
            "user.email=canon@example.com",
            "-c",
            "user.name=Canon Tests",
            "commit",
            "--allow-empty",
            "-m",
            "work",
        )


def _approved_tool_response(plan_text: str, saved_path: Path | None) -> str:
    saved_line = f"Your plan has been saved to: {saved_path}\n" if saved_path else ""
    return (
        "User has approved your plan. You can now start coding.\n\n"
        + saved_line
        + "You can refer back to it if needed during implementation.\n\n"
        "## Approved Plan:\n" + plan_text
    )


def _invoke_main(payload: dict[str, object]) -> None:
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            save_plan.main()


class PlanBodyParsingTests(unittest.TestCase):
    def test_no_approved_marker_is_not_an_approval(self) -> None:
        self.assertIsNone(save_plan._plan_body("keep planning, please revise"))

    def test_embedded_body_used_when_no_saved_path_line(self) -> None:
        response = _approved_tool_response(PLAN_WITH_SECTIONS, saved_path=None)
        body = save_plan._plan_body(response)
        assert body is not None
        self.assertEqual(body.strip(), PLAN_WITH_SECTIONS.strip())

    def test_saved_path_preferred_over_embedded_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saved = Path(tmp) / "plan.md"
            saved.write_text("the real, on-disk plan", encoding="utf-8")
            response = _approved_tool_response("a stale embedded copy", saved)
            self.assertEqual(save_plan._plan_body(response), "the real, on-disk plan")

    def test_falls_back_to_embedded_copy_when_path_unreadable(self) -> None:
        response = _approved_tool_response(
            PLAN_WITH_SECTIONS, Path("/nonexistent/plan.md")
        )
        body = save_plan._plan_body(response)
        assert body is not None
        self.assertEqual(body.strip(), PLAN_WITH_SECTIONS.strip())


class RequiredSectionTests(unittest.TestCase):
    def test_both_sections_present_reports_nothing_missing(self) -> None:
        self.assertEqual(save_plan._missing_required_sections(PLAN_WITH_SECTIONS), [])

    def test_missing_non_goals_is_reported(self) -> None:
        self.assertEqual(
            save_plan._missing_required_sections(PLAN_MISSING_NON_GOALS),
            ["non-goals"],
        )

    def test_empty_verification_is_reported(self) -> None:
        self.assertEqual(
            save_plan._missing_required_sections(PLAN_EMPTY_VERIFICATION),
            ["verification"],
        )


class MainTests(unittest.TestCase):
    def test_writes_plan_with_header_and_verify_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "feature/widget")
            (root / ".canon").mkdir()
            (root / ".canon" / "config.json").write_text(
                json.dumps({"verify": "just test"}), encoding="utf-8"
            )
            response = _approved_tool_response(PLAN_WITH_SECTIONS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            plan_path = root / ".canon" / "plans" / "feature/widget.md"
            self.assertTrue(plan_path.exists())
            content = plan_path.read_text(encoding="utf-8")
            self.assertIn("status: approved", content)
            self.assertIn('verify: "just test"', content)
            self.assertIn("scope:", content)
            self.assertIn("done:", content)
            self.assertIn("parent:", content)
            self.assertIn("## Non-goals", content)
            self.assertNotIn("notes:", content)

    def test_leaves_verify_blank_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "feature/widget")
            response = _approved_tool_response(PLAN_WITH_SECTIONS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            content = (root / ".canon" / "plans" / "feature/widget.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("verify:\n", content)

    def test_derives_base_sha_from_git(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "feature/widget")
            expected_base = subprocess.run(
                ["git", "merge-base", "HEAD", "main"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()[:9]
            response = _approved_tool_response(PLAN_WITH_SECTIONS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            content = (root / ".canon" / "plans" / "feature/widget.md").read_text(
                encoding="utf-8"
            )
            self.assertIn(f'base: "{expected_base}"', content)

    def test_base_is_blank_when_git_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            response = _approved_tool_response(PLAN_WITH_SECTIONS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            plan_path = root / ".canon" / "plans" / "HEAD.md"
            self.assertTrue(plan_path.exists())
            self.assertIn("base:\n", plan_path.read_text(encoding="utf-8"))

    def test_notes_missing_section(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "feature/widget")
            response = _approved_tool_response(PLAN_MISSING_NON_GOALS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            content = (root / ".canon" / "plans" / "feature/widget.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Non-goals section is missing or empty", content)

    def test_overwrites_an_existing_plan_for_the_same_branch(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "feature/widget")
            plan_dir = root / ".canon" / "plans"
            plan_dir.mkdir(parents=True)
            (plan_dir / "feature/widget.md").parent.mkdir(parents=True, exist_ok=True)
            (plan_dir / "feature/widget.md").write_text("stale", encoding="utf-8")
            response = _approved_tool_response(PLAN_WITH_SECTIONS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            content = (plan_dir / "feature/widget.md").read_text(encoding="utf-8")
            self.assertNotEqual(content, "stale")
            self.assertIn("Do the thing.", content)

    def test_noop_when_tool_response_is_not_an_approval(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "feature/widget")

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": "the user chose to keep planning",
                }
            )

            self.assertFalse((root / ".canon").exists())

    def test_noop_when_tool_name_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "feature/widget")
            response = _approved_tool_response(PLAN_WITH_SECTIONS, saved_path=None)

            _invoke_main(
                {"cwd": str(root), "tool_name": "Edit", "tool_response": response}
            )

            self.assertFalse((root / ".canon").exists())


if __name__ == "__main__":
    unittest.main()
