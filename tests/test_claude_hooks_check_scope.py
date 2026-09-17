# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/check_scope.py.

Covers the glob matcher's `**` handling, the scope/Non-goals departure
signals independently and together, the no-signal no-op (blank scope,
empty Non-goals), and the first-departure vs. sustained-departure
escalation via the session-scoped counter -- mirroring
test_claude_hooks_stop.py's own consecutive-counter test style.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import check_scope
import save_plan

SAVED_PLAN_WITH_SCOPE = """---
status: approved
base: "a41f0c9"
scope: [src/slugs/**, tests/slugs/**]
done:
verify:
parent:
---

## Approach
Do it.

## Non-goals
- Not touching docs/readme.md.

## Verification
1. Run tests.
"""

SAVED_PLAN_NO_SIGNAL = """---
status: approved
base: "a41f0c9"
scope:
done:
verify:
parent:
---

## Approach
Do it.

## Verification
1. Run tests.
"""


class GlobMatchTests(unittest.TestCase):
    def test_exact_match(self) -> None:
        self.assertTrue(check_scope._glob_match("src/foo.py", "src/foo.py"))

    def test_single_star_within_a_segment(self) -> None:
        self.assertTrue(check_scope._glob_match("src/*.py", "src/foo.py"))
        self.assertFalse(check_scope._glob_match("src/*.py", "src/sub/foo.py"))

    def test_double_star_matches_any_depth(self) -> None:
        self.assertTrue(check_scope._glob_match("src/slugs/**", "src/slugs/a.py"))
        self.assertTrue(
            check_scope._glob_match("src/slugs/**", "src/slugs/deep/nested/a.py")
        )
        self.assertTrue(check_scope._glob_match("src/slugs/**", "src/slugs"))

    def test_double_star_does_not_match_a_sibling_directory(self) -> None:
        self.assertFalse(check_scope._glob_match("src/slugs/**", "src/other/a.py"))


class ParseScopePatternsTests(unittest.TestCase):
    def test_bracketed_list(self) -> None:
        self.assertEqual(
            check_scope._parse_scope_patterns("[src/slugs/**, tests/slugs/**]"),
            ["src/slugs/**", "tests/slugs/**"],
        )

    def test_single_pattern_without_brackets(self) -> None:
        self.assertEqual(check_scope._parse_scope_patterns("src/**"), ["src/**"])

    def test_blank_yields_empty_list(self) -> None:
        self.assertEqual(check_scope._parse_scope_patterns(""), [])


class MentionedInNonGoalsTests(unittest.TestCase):
    def test_full_path_mentioned(self) -> None:
        self.assertTrue(
            check_scope._mentioned_in_non_goals(
                "Not touching docs/readme.md.", "docs/readme.md"
            )
        )

    def test_filename_alone_mentioned(self) -> None:
        self.assertTrue(
            check_scope._mentioned_in_non_goals(
                "Not touching readme.md.", "docs/readme.md"
            )
        )

    def test_unrelated_text_is_not_a_match(self) -> None:
        self.assertFalse(
            check_scope._mentioned_in_non_goals(
                "Not touching anything else.", "docs/readme.md"
            )
        )

    def test_blank_non_goals_is_never_a_match(self) -> None:
        self.assertFalse(check_scope._mentioned_in_non_goals("", "docs/readme.md"))


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
    _activate(root)


def _activate(root: Path) -> None:
    """Give `root` a verification signal.

    Canon is inert without one (docs/plan.md §07, "No signal, no
    Canon"), so a fixture with no `verify` command exercises the inert
    path rather than the behaviour under test. Every test here that is
    not specifically about going inert calls this.
    """
    config_path = root / ".canon" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"verify": "true"}), encoding="utf-8")


def _write_plan(root: Path, branch: str, text: str) -> None:
    plan_path = root / ".canon" / "plans" / f"{branch}.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(text, encoding="utf-8")


def _invoke_main(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            with mock.patch("sys.stdout", buffer):
                check_scope.main()
    return buffer.getvalue()


class MainTests(unittest.TestCase):
    def test_uses_the_redirected_branch_plan_for_a_features_prefixed_branch(
        self,
    ) -> None:
        """`plan_header.branch_plan_path` redirects a `features/<x>`
        branch's own plan to `.canon/plans/branches/features/<x>.md`, to
        avoid colliding with a feature plan of the same slug at
        `.canon/plans/features/<x>.md` (see plan_header.py's module
        docstring). This hook must compare against the redirected plan --
        comparing against the plain `.canon/plans/<branch>.md` formula
        instead means comparing against a feature-level `## Non-goals`
        that was never written with these files in mind (or, as here, no
        `## Non-goals` at all)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "features/widget")
            feature_plan = root / ".canon" / "plans" / "features" / "widget.md"
            feature_plan.parent.mkdir(parents=True)
            feature_plan.write_text(
                "---\nstatus: approved\nsteps:\n---\n\n## Steps\n- a: x\n",
                encoding="utf-8",
            )
            branch_plan = (
                root / ".canon" / "plans" / "branches" / "features" / "widget.md"
            )
            branch_plan.parent.mkdir(parents=True)
            branch_plan.write_text(SAVED_PLAN_WITH_SCOPE, encoding="utf-8")

            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "docs" / "readme.md")},
                }
            )
            self.assertIn("Non-goals", output)

    def test_noop_when_no_plan_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "src" / "foo.py")},
                }
            )
            self.assertEqual(output, "")

    def test_noop_when_no_scope_or_non_goals_declared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(root, "feature/widget", SAVED_PLAN_NO_SIGNAL)
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "anything.py")},
                }
            )
            self.assertEqual(output, "")

    def test_in_scope_edit_produces_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(root, "feature/widget", SAVED_PLAN_WITH_SCOPE)
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "src" / "slugs" / "a.py")},
                }
            )
            self.assertEqual(output, "")

    def test_first_departure_is_a_context_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(root, "feature/widget", SAVED_PLAN_WITH_SCOPE)
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "unrelated" / "thing.py")},
                }
            )
            payload = json.loads(output)
            self.assertEqual(
                payload["hookSpecificOutput"]["hookEventName"], "PostToolUse"
            )
            self.assertIn(
                "Possible scope departure",
                payload["hookSpecificOutput"]["additionalContext"],
            )

    def test_non_goals_mention_is_a_departure_even_inside_declared_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(root, "feature/widget", SAVED_PLAN_WITH_SCOPE)
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "docs" / "readme.md")},
                }
            )
            payload = json.loads(output)
            self.assertIn(
                "Non-goals", payload["hookSpecificOutput"]["additionalContext"]
            )

    def test_sustained_departure_logs_a_decision(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as scratch,
        ):
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(root, "feature/widget", SAVED_PLAN_WITH_SCOPE)
            payload = {
                "cwd": str(root),
                "tool_name": "Edit",
                "tool_input": {"file_path": str(root / "unrelated" / "thing.py")},
                "scratchpad_dir": scratch,
            }
            _invoke_main(payload)
            _invoke_main(payload)
            output = _invoke_main(payload)

            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            self.assertTrue(log_path.exists())
            record = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["hook"], "check_scope.py")
            self.assertEqual(record["decision"], "departure")
            self.assertIn("Sustained scope departure", output)

    def test_an_in_scope_edit_resets_the_counter(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as scratch,
        ):
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(root, "feature/widget", SAVED_PLAN_WITH_SCOPE)
            out_of_scope_payload = {
                "cwd": str(root),
                "tool_name": "Edit",
                "tool_input": {"file_path": str(root / "unrelated" / "thing.py")},
                "scratchpad_dir": scratch,
            }
            in_scope_payload = {
                "cwd": str(root),
                "tool_name": "Edit",
                "tool_input": {"file_path": str(root / "src" / "slugs" / "a.py")},
                "scratchpad_dir": scratch,
            }
            _invoke_main(out_of_scope_payload)
            _invoke_main(out_of_scope_payload)
            _invoke_main(in_scope_payload)
            output = _invoke_main(out_of_scope_payload)

            self.assertIn("Possible scope departure", output)
            self.assertNotIn("Sustained", output)

    def test_noop_when_tool_name_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(root, "feature/widget", SAVED_PLAN_WITH_SCOPE)
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                }
            )
            self.assertEqual(output, "")

    def test_noop_when_file_path_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(root, "feature/widget", SAVED_PLAN_WITH_SCOPE)
            output = _invoke_main(
                {"cwd": str(root), "tool_name": "Edit", "tool_input": {}}
            )
            self.assertEqual(output, "")


class InertWithoutVerificationSignalTests(unittest.TestCase):
    """docs/plan.md §07: "Not the gate alone -- the whole plugin."

    See docs/decisions/0001-what-inert-means.md for the two hooks this
    deliberately does not apply to.
    """

    def test_a_scope_departure_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            _write_plan(
                root,
                "feature/widget",
                "---\nstatus: approved\nscope: [src/widget/**]\n---\n\n"
                "## Non-goals\nDo not touch the parser.\n",
            )
            (root / ".canon" / "config.json").unlink()
            output = _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(root / "src" / "parser.py")},
                }
            )
            self.assertEqual(output, "")


class ScopeFromADerivedHeaderTests(unittest.TestCase):
    """The glob half of this hook, end to end from an approved plan.

    `save_plan.py` wrote `scope:` blank unconditionally until §06's
    derivation landed, so `_glob_match` was unreachable in practice no
    matter how well it was unit-tested: `patterns` was always empty and
    the `out_of_scope` branch never ran. These exercise the real path --
    a plan approved with a `## Scope` section, then an edit checked
    against it.
    """

    def _approve(self, root: Path, branch: str, scope_section: str) -> None:
        body = (
            f"## Scope\n{scope_section}\n\n"
            "## Non-goals\nDo not rewrite the parser.\n\n"
            "## Verification\njust test\n"
        )
        response = (
            "User has approved your plan. You can now start coding.\n\n"
            "## Approved Plan:\n" + body
        )
        with mock.patch.object(
            sys,
            "stdin",
            io.StringIO(
                json.dumps(
                    {
                        "cwd": str(root),
                        "tool_name": "ExitPlanMode",
                        "tool_response": response,
                    }
                )
            ),
        ):
            with mock.patch("sys.exit"):
                save_plan.main()

    def _edit(self, root: Path, relative: str) -> str:
        return _invoke_main(
            {
                "cwd": str(root),
                "tool_name": "Edit",
                "tool_input": {"file_path": str(root / relative)},
            }
        )

    def test_an_in_scope_edit_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            self._approve(root, "feature/widget", "- src/widget/**")
            self.assertEqual(self._edit(root, "src/widget/core.py"), "")

    def test_an_out_of_scope_edit_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            self._approve(root, "feature/widget", "- src/widget/**")
            output = self._edit(root, "src/parser/lexer.py")
            self.assertIn("Possible scope departure", output)
            self.assertIn("src/parser/lexer.py", output)

    def test_a_prose_scope_section_reports_nothing(self) -> None:
        """No pattern is derived from prose, so there is nothing to
        depart from -- the hook must not manufacture a departure."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            self._approve(root, "feature/widget", "Just the widget module.")
            self.assertEqual(self._edit(root, "src/parser/lexer.py"), "")


if __name__ == "__main__":
    unittest.main()
