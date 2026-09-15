# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/codex/hooks/normalize_plan.py -- the plan-persistence
hook that has no Claude Code counterpart to regression-test against (see
its own module docstring, and save_plan.py's, for why: Codex has no
`ExitPlanMode` tool, so this hook reacts to the agent writing the plan
file directly instead of to an approved tool call).

Covers deriving a branch plan's header from its body, deriving a feature
plan's header, idempotency on a second run (this hook fires on the very
write it performs, so it must recognize its own output and do nothing),
the missing-required-sections note, a non-plan file left untouched, and
the multi-path `changes` list shape.
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
