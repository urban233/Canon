# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/codex/hooks/normalize_plan.py -- the plan-persistence
hook that has no Claude Code counterpart to regression-test against (see
its own module docstring, and save_plan.py's, for why: Codex has no
`ExitPlanMode` tool, so this hook reacts to the agent writing the plan
file directly instead of to an approved tool call).

Covers deriving a branch plan's header from its body, deriving a feature
plan's header, idempotency on a second run (this hook fires on the very
write it performs, so it must recognize its own output and do nothing),
the missing-required-sections note, a non-plan file left untouched, the
multi-path `changes` list shape, and (`BranchNamespaceCollisionTests`) a
branch under the reserved "features/" prefix that the `plan` skill wrote
straight to `.canon/plans/features/<x>.md`, indistinguishable on sight
from a feature plan of the same slug.
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

import normalize_plan

PLAN_BODY = """# Widget

## Scope
- `src/widget/**`

## Done
Widget renders without error.

## Non-goals
Does not touch the legacy dashboard.

## Verification
`pytest tests/widget -x`
"""

PLAN_BODY_MISSING_NON_GOALS = """# Widget

## Done
Widget renders without error.

## Verification
`pytest tests/widget -x`
"""

FEATURE_PLAN_BODY = """# Widgets v2

## Steps
- widget-a: build the widget
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


def _relocated_widget_plan(root: Path) -> Path:
    """Where a "features/widget" branch's plan ends up once
    `normalize_plan.py` relocates it out of the feature-plan namespace."""
    return root / ".canon" / "plans" / "branches" / "features" / "widget.md"


def _write_payload(tool_input: dict[str, object]) -> dict[str, object]:
    return {"tool_name": "Write", "tool_input": tool_input}


def _invoke_main(root: Path, tool_input: dict[str, object]) -> str:
    """Run the hook, returning whatever `additionalContext` it emitted
    (or "" for the silent path)."""
    payload = {"cwd": str(root), **_write_payload(tool_input)}
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            with mock.patch("sys.stdout", buffer):
                normalize_plan.main()
    raw = buffer.getvalue()
    if not raw:
        return ""
    return json.loads(raw)["hookSpecificOutput"]["additionalContext"]


class BranchPlanTests(unittest.TestCase):
    def test_header_is_derived_from_the_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            plan_path = root / ".canon" / "plans" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN_BODY)

            _invoke_main(root, {"file_path": str(plan_path)})

            result = plan_path.read_text()
            self.assertTrue(result.startswith("---\nstatus: approved\n"))
            self.assertIn('scope: "[src/widget/**]"', result)
            self.assertIn('done: "Widget renders without error"', result)
            self.assertIn('verify: "pytest tests/widget -x"', result)
            self.assertIn("# Widget", result)

    def test_a_previously_normalized_file_is_left_unchanged_on_a_second_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            plan_path = root / ".canon" / "plans" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN_BODY)

            _invoke_main(root, {"file_path": str(plan_path)})
            first_result = plan_path.read_text()
            mtime_before = plan_path.stat().st_mtime_ns

            _invoke_main(root, {"file_path": str(plan_path)})
            second_result = plan_path.read_text()

            self.assertEqual(first_result, second_result)
            # Not just byte-equal -- genuinely not rewritten, since a
            # rewrite of identical content would still bump mtime.
            self.assertEqual(plan_path.stat().st_mtime_ns, mtime_before)

    def test_an_agent_authored_header_is_replaced_not_trusted(self) -> None:
        """docs/plan.md §07's "wrong-but-plausible is worse than absent"
        applies as much to a header the agent invented as to one this
        hook would have guessed -- see normalize_plan.py's docstring."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            plan_path = root / ".canon" / "plans" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            hand_written = (
                '---\nstatus: approved\nscope: "[wrong/**]"\n---\n\n' + PLAN_BODY
            )
            plan_path.write_text(hand_written)

            _invoke_main(root, {"file_path": str(plan_path)})

            result = plan_path.read_text()
            self.assertIn('scope: "[src/widget/**]"', result)
            self.assertNotIn("wrong/**", result)

    def test_missing_required_sections_are_surfaced_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            plan_path = root / ".canon" / "plans" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN_BODY_MISSING_NON_GOALS)

            context = _invoke_main(root, {"file_path": str(plan_path)})

            self.assertIn("Non-goals", context)
            self.assertIn(".canon/plans/widget.md", context)


class FeaturePlanTests(unittest.TestCase):
    def test_feature_header_is_derived_from_a_non_empty_steps_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            plan_path = root / ".canon" / "plans" / "features" / "widgets-v2.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(FEATURE_PLAN_BODY)

            _invoke_main(root, {"file_path": str(plan_path)})

            result = plan_path.read_text()
            self.assertEqual(
                result, "---\nstatus: approved\nsteps:\n---\n\n" + FEATURE_PLAN_BODY
            )

    def test_a_previously_normalized_feature_plan_is_left_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            plan_path = root / ".canon" / "plans" / "features" / "widgets-v2.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(FEATURE_PLAN_BODY)

            _invoke_main(root, {"file_path": str(plan_path)})
            first_result = plan_path.read_text()
            _invoke_main(root, {"file_path": str(plan_path)})

            self.assertEqual(plan_path.read_text(), first_result)


class BranchNamespaceCollisionTests(unittest.TestCase):
    """The `plan` skill tells the agent to write a branch plan to
    `.canon/plans/<branch>.md` literally, with no knowledge that
    "features/" is reserved for feature plans (see plan_header.py's
    docstring) -- so a branch named e.g. "features/widget" lands the
    agent's own write at exactly the path a feature plan titled "Widget"
    would use, before this hook ever runs. `normalize_plan.py` cannot
    undo that write, but it can stop the collision from staying: a file
    under `.canon/plans/features/` with no `## Steps` is not a feature
    plan and is moved to where `plan_header.branch_plan_path` would have
    put a colliding branch's plan directly.
    """

    def test_a_features_prefixed_branch_plan_is_relocated_and_announced(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "features/widget")
            naive_path = root / ".canon" / "plans" / "features" / "widget.md"
            naive_path.parent.mkdir(parents=True)
            naive_path.write_text(PLAN_BODY)

            context = _invoke_main(root, {"file_path": str(naive_path)})

            self.assertIn("features/widget", context)
            self.assertFalse(naive_path.exists())
            relocated = _relocated_widget_plan(root)
            self.assertTrue(relocated.exists())
            result = relocated.read_text()
            self.assertTrue(result.startswith("---\nstatus: approved\n"))
            self.assertIn('scope: "[src/widget/**]"', result)

    def test_relocation_and_a_missing_section_are_named_in_one_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "features/widget")
            naive_path = root / ".canon" / "plans" / "features" / "widget.md"
            naive_path.parent.mkdir(parents=True)
            naive_path.write_text(PLAN_BODY_MISSING_NON_GOALS)

            context = _invoke_main(root, {"file_path": str(naive_path)})

            self.assertIn("features/widget", context)
            self.assertIn("Non-goals", context)
            relocated = _relocated_widget_plan(root)
            self.assertTrue(relocated.exists())

    def test_the_relocated_file_is_stable_on_a_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "features/widget")
            naive_path = root / ".canon" / "plans" / "features" / "widget.md"
            naive_path.parent.mkdir(parents=True)
            naive_path.write_text(PLAN_BODY)

            _invoke_main(root, {"file_path": str(naive_path)})
            relocated = _relocated_widget_plan(root)
            first_result = relocated.read_text()
            mtime_before = relocated.stat().st_mtime_ns

            second_context = _invoke_main(root, {"file_path": str(relocated)})

            self.assertEqual(second_context, "")
            self.assertEqual(relocated.read_text(), first_result)
            self.assertEqual(relocated.stat().st_mtime_ns, mtime_before)

    def test_a_path_under_features_with_steps_is_still_a_feature_plan(self) -> None:
        """A genuine feature plan is never relocated, even though its own
        path is indistinguishable from a colliding branch's by name
        alone -- `## Steps` is what actually decides it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            plan_path = root / ".canon" / "plans" / "features" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(FEATURE_PLAN_BODY)

            _invoke_main(root, {"file_path": str(plan_path)})

            self.assertTrue(plan_path.exists())
            self.assertIn("steps:", plan_path.read_text())
            self.assertFalse((root / ".canon" / "plans" / "branches").exists())

    def test_a_features_prefixed_plan_on_a_different_branch_is_not_exiled(
        self,
    ) -> None:
        """No `## Steps` is not proof of a colliding branch's plan -- a
        genuine feature plan mid-draft, or headed "## Steps (ordered)"
        rather than the exact heading this hook looks for, reads the
        same way. On `main` (not `features/widget`), this can only be a
        feature plan, so it must never be moved and re-headed as a
        branch plan -- that would fabricate a `base:`/`scope:` for a
        branch that doesn't exist and leave `.canon/plans/features/`
        with a hole in it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            plan_path = root / ".canon" / "plans" / "features" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            mid_draft = "# Widget\n\n## Steps (ordered)\n1. one\n"
            plan_path.write_text(mid_draft)

            context = _invoke_main(root, {"file_path": str(plan_path)})

            self.assertEqual(context, "")
            self.assertTrue(plan_path.exists())
            self.assertNotIn("scope:", plan_path.read_text())
            self.assertFalse((root / ".canon" / "plans" / "branches").exists())

    def test_a_pre_existing_relocated_plan_is_never_clobbered(self) -> None:
        """`destination.exists()` must never be `replace()`d over --
        whatever is already saved there survives, and the candidate is
        left where it is instead."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "features/widget")
            relocated = _relocated_widget_plan(root)
            relocated.parent.mkdir(parents=True)
            relocated.write_text("EXISTING RELOCATED PLAN -- do not overwrite")

            naive_path = root / ".canon" / "plans" / "features" / "widget.md"
            naive_path.parent.mkdir(parents=True)
            naive_path.write_text(PLAN_BODY)

            context = _invoke_main(root, {"file_path": str(naive_path)})

            self.assertEqual(
                relocated.read_text(), "EXISTING RELOCATED PLAN -- do not overwrite"
            )
            self.assertTrue(naive_path.exists())
            self.assertIn("already saved there", context)

    def test_a_branch_literally_named_branches_slash_x_is_not_misderived(
        self,
    ) -> None:
        """A genuine branch named "branches/widget" writes its own,
        unrelated plan at `.canon/plans/branches/widget.md` -- the same
        shape of path the collision redirect uses. Stripping the
        redirect prefix there would derive branch "widget" instead of
        the true "branches/widget"."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "branches/widget")
            plan_path = root / ".canon" / "plans" / "branches" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN_BODY_MISSING_NON_GOALS)

            context = _invoke_main(root, {"file_path": str(plan_path)})

            self.assertIn(".canon/plans/branches/widget.md", context)

    def test_a_singular_feature_branch_plan_is_not_relocated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            plan_path = root / ".canon" / "plans" / "feature" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN_BODY)

            context = _invoke_main(root, {"file_path": str(plan_path)})

            self.assertNotIn("features/", context)
            self.assertTrue(plan_path.exists())
            self.assertFalse((root / ".canon" / "plans" / "branches").exists())

    def test_a_plain_branch_plan_is_not_relocated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            plan_path = root / ".canon" / "plans" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN_BODY)

            _invoke_main(root, {"file_path": str(plan_path)})

            self.assertTrue(plan_path.exists())
            self.assertFalse((root / ".canon" / "plans" / "branches").exists())


class NoOpTests(unittest.TestCase):
    def test_a_file_outside_canon_plans_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            other = root / "src" / "widget" / "app.py"
            other.parent.mkdir(parents=True)
            other.write_text("print('hi')\n")

            _invoke_main(root, {"file_path": str(other)})

            self.assertEqual(other.read_text(), "print('hi')\n")

    def test_a_non_edit_tool_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            plan_path = root / ".canon" / "plans" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN_BODY)

            payload = {
                "cwd": str(root),
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi"},
            }
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                with mock.patch("sys.exit"):
                    normalize_plan.main()

            self.assertEqual(plan_path.read_text(), PLAN_BODY)

    def test_malformed_payload_is_a_silent_no_op(self) -> None:
        with mock.patch.object(sys, "stdin", io.StringIO("not json")):
            with mock.patch("sys.exit"):
                normalize_plan.main()  # must not raise

    def test_a_changes_list_only_normalizes_the_plan_path_within_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            plan_path = root / ".canon" / "plans" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(PLAN_BODY)
            other = root / "src" / "widget" / "app.py"
            other.parent.mkdir(parents=True)
            other.write_text("print('hi')\n")

            payload = {
                "cwd": str(root),
                "tool_name": "apply_patch",
                "tool_input": {
                    "changes": [
                        {"path": str(other)},
                        {"path": str(plan_path)},
                    ]
                },
            }
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                with mock.patch("sys.exit"):
                    normalize_plan.main()

            self.assertEqual(other.read_text(), "print('hi')\n")
            self.assertTrue(plan_path.read_text().startswith("---\nstatus: approved"))


if __name__ == "__main__":
    unittest.main()
