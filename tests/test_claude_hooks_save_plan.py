# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/save_plan.py.

Covers reading the approved plan (preferring the on-disk file over the
embedded copy), the derived header (`status`, `base`, `verify` filled in;
`scope`/`done`/`parent` left blank), the missing-required-section notes,
the silent no-op on anything that isn't an approval, (`FeaturePlanTests`)
the feature-plan path a non-empty `## Steps` section triggers instead, and
(`BranchNamespaceCollisionTests`) the "features/"-prefixed branch that
would otherwise collide with that same feature-plan namespace.
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

import _common
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

PLAN_WITH_STEPS = """# Public Permalinks

## Why
People need to cite datasets.

## Success
A permalink resolves for any dataset, forever.

## Non-goals
- Not migrating existing internal links.

## Shape
A slug model and a resolver.

## Steps
1. Slug model
2. Resolver
3. Migration
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


def _approved_payload(root: Path, plan_text: str) -> dict[str, object]:
    return {
        "cwd": str(root),
        "tool_name": "ExitPlanMode",
        "tool_response": _approved_tool_response(plan_text, saved_path=None),
    }


def _invoke_main(payload: dict[str, object]) -> str:
    """Run the hook, returning whatever `additionalContext` it emitted
    (or "" for the silent path)."""
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            with mock.patch("sys.stdout", buffer):
                save_plan.main()
    raw = buffer.getvalue()
    if not raw:
        return ""
    return json.loads(raw)["hookSpecificOutput"]["additionalContext"]


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
    def test_verify_is_not_copied_from_config(self) -> None:
        """The config value must NOT be pinned into the header.

        Once §07's "overrides it for that branch" is honoured, a copy
        taken at approval time stops being a record and becomes a pin:
        every later edit to `.canon/config.json` would be silently
        ignored on every branch whose plan predates it. A blank
        `verify:` is what lets the config keep answering.
        """
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "feature/widget")
            (root / ".canon").mkdir(exist_ok=True)
            (root / ".canon" / "config.json").write_text(
                json.dumps({"verify": "just test"}), encoding="utf-8"
            )
            _invoke_main(_approved_payload(root, PLAN_WITH_SECTIONS))

            content = (root / ".canon" / "plans" / "feature/widget.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("status: approved", content)
            self.assertIn("\nverify:\n", content)
            self.assertNotIn("just test", content)

    def test_writes_plan_with_header(self) -> None:
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


class FeaturePlanTests(unittest.TestCase):
    def test_saves_to_the_features_directory_with_a_slugified_title(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "main")
            response = _approved_tool_response(PLAN_WITH_STEPS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            plan_path = root / ".canon" / "plans" / "features" / "public-permalinks.md"
            self.assertTrue(plan_path.exists())

    def test_header_has_status_and_a_blank_steps_field(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "main")
            response = _approved_tool_response(PLAN_WITH_STEPS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            content = (
                root / ".canon" / "plans" / "features" / "public-permalinks.md"
            ).read_text(encoding="utf-8")
            self.assertIn("status: approved", content)
            self.assertIn("steps:\n", content)
            self.assertNotIn("scope:", content)
            self.assertNotIn("base:", content)

    def test_body_steps_section_rides_through_unaltered(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "main")
            response = _approved_tool_response(PLAN_WITH_STEPS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            content = (
                root / ".canon" / "plans" / "features" / "public-permalinks.md"
            ).read_text(encoding="utf-8")
            self.assertIn("## Steps", content)
            self.assertIn("1. Slug model", content)

    def test_falls_back_to_feature_when_no_title_present(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "main")
            untitled = "## Steps\n1. One step\n"
            response = _approved_tool_response(untitled, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            plan_path = root / ".canon" / "plans" / "features" / "feature.md"
            self.assertTrue(plan_path.exists())

    def test_overwrites_an_existing_feature_plan_of_the_same_slug(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            _init_repo(root, "main")
            features_dir = root / ".canon" / "plans" / "features"
            features_dir.mkdir(parents=True)
            (features_dir / "public-permalinks.md").write_text(
                "stale", encoding="utf-8"
            )
            response = _approved_tool_response(PLAN_WITH_STEPS, saved_path=None)

            _invoke_main(
                {
                    "cwd": str(root),
                    "tool_name": "ExitPlanMode",
                    "tool_response": response,
                }
            )

            content = (features_dir / "public-permalinks.md").read_text(
                encoding="utf-8"
            )
            self.assertNotEqual(content, "stale")
            self.assertIn("Slug model", content)

    def test_a_plan_without_steps_still_takes_the_branch_path(self) -> None:
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

            self.assertTrue((root / ".canon" / "plans" / "feature/widget.md").exists())
            self.assertFalse((root / ".canon" / "plans" / "features").exists())


class BranchNamespaceCollisionTests(unittest.TestCase):
    """A branch under the reserved "features/" prefix maps, via the plain
    `<branch>.md` formula every other branch uses, to exactly the path a
    feature plan of the same name uses -- `.canon/plans/features/<x>.md`.
    Writing there would silently overwrite that feature plan, the exact
    failure Invariant II rules out everywhere else (see plan_header.py's
    docstring). `branch_plan_path` redirects it instead; this covers that
    it does, that the redirect is surfaced once, that a pre-existing
    feature plan of the same name survives untouched, and that the
    far-more-common singular "feature/x" convention is never affected.
    """

    def test_a_features_prefixed_branch_is_redirected_and_announced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "features/public-permalinks")
            message = self._approve(root, PLAN_WITH_SECTIONS)

            self.assertIn("features/public-permalinks", message)
            self.assertIn(
                ".canon/plans/branches/features/public-permalinks.md", message
            )

            redirected = (
                root
                / ".canon"
                / "plans"
                / "branches"
                / "features"
                / "public-permalinks.md"
            )
            self.assertTrue(redirected.exists())
            self.assertIn("Do the thing.", redirected.read_text(encoding="utf-8"))
            naive_path = (
                root / ".canon" / "plans" / "features" / "public-permalinks.md"
            )
            self.assertFalse(naive_path.exists())

    def test_a_pre_existing_feature_plan_of_the_same_name_is_left_untouched(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "features/public-permalinks")
            features_dir = root / ".canon" / "plans" / "features"
            features_dir.mkdir(parents=True)
            existing = features_dir / "public-permalinks.md"
            existing.write_text("the real feature plan, untouched", encoding="utf-8")

            self._approve(root, PLAN_WITH_SECTIONS)

            self.assertEqual(
                existing.read_text(encoding="utf-8"), "the real feature plan, untouched"
            )

    def test_a_singular_feature_branch_does_not_collide(self) -> None:
        """"feature/x" (singular -- the far more common convention) has a
        different first path segment from "features" and is unaffected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            message = self._approve(root, PLAN_WITH_SECTIONS)

            self.assertEqual(message, "")
            self.assertTrue(
                (root / ".canon" / "plans" / "feature" / "widget.md").exists()
            )
            self.assertFalse((root / ".canon" / "plans" / "branches").exists())

    def test_a_plain_branch_does_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "widget")
            message = self._approve(root, PLAN_WITH_SECTIONS)

            self.assertEqual(message, "")
            self.assertTrue((root / ".canon" / "plans" / "widget.md").exists())
            self.assertFalse((root / ".canon" / "plans" / "branches").exists())

    def test_a_genuine_feature_plan_still_saves_under_features_as_before(self) -> None:
        """A `## Steps`-bearing plan approved on any branch still takes
        the feature-plan path exactly as before -- the collision redirect
        only ever applies to a *branch* plan."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "features/public-permalinks")
            message = self._approve(root, PLAN_WITH_STEPS)

            self.assertEqual(message, "")
            plan_path = root / ".canon" / "plans" / "features" / "public-permalinks.md"
            self.assertTrue(plan_path.exists())
            self.assertFalse((root / ".canon" / "plans" / "branches").exists())

    def _approve(self, root: Path, body: str) -> str:
        return _invoke_main(_approved_payload(root, body))


class DerivedHeaderFieldTests(unittest.TestCase):
    """`scope:`, `done:` and `parent:` read back out of the plan body.

    Before this existed the hook wrote all three blank unconditionally,
    which left `check_scope.py`'s glob matcher unreachable and the
    `frame` -> branch-plan link unmade. See §06.
    """

    def test_scope_from_a_bulleted_list(self) -> None:
        patterns = save_plan._scope_patterns("- src/slugs/**\n- tests/slugs/**")
        self.assertEqual(patterns, ["src/slugs/**", "tests/slugs/**"])

    def test_scope_from_a_comma_separated_line(self) -> None:
        patterns = save_plan._scope_patterns("src/slugs/**, tests/slugs/**")
        self.assertEqual(patterns, ["src/slugs/**", "tests/slugs/**"])

    def test_scope_keeps_the_backticked_token_and_drops_commentary(self) -> None:
        patterns = save_plan._scope_patterns("- `src/slugs/**` -- the slug module")
        self.assertEqual(patterns, ["src/slugs/**"])

    def test_scope_ignores_prose(self) -> None:
        """A wrong scope is worse than an absent one: every edit outside
        it is reported as a departure."""
        self.assertEqual(
            save_plan._scope_patterns("This touches the slug module and its tests."),
            [],
        )

    def test_scope_deduplicates(self) -> None:
        self.assertEqual(
            save_plan._scope_patterns("- src/a.py\n- src/a.py"), ["src/a.py"]
        )

    def test_done_takes_the_first_line_only(self) -> None:
        done = save_plan._done_line("duplicate slugs raise\n\nmore detail here")
        self.assertEqual(done, "duplicate slugs raise")

    def test_done_strips_a_bullet(self) -> None:
        self.assertEqual(save_plan._done_line("- slugs raise"), "slugs raise")

    def test_done_is_none_for_an_empty_section(self) -> None:
        self.assertIsNone(save_plan._done_line("   \n\n"))

    def test_parent_resolves_an_existing_feature_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            features = root / ".canon" / "plans" / "features"
            features.mkdir(parents=True)
            (features / "permalinks.md").write_text("x", encoding="utf-8")
            self.assertEqual(
                save_plan._parent_path(root, "permalinks.md"),
                "features/permalinks.md",
            )

    def test_parent_accepts_a_bare_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            features = root / ".canon" / "plans" / "features"
            features.mkdir(parents=True)
            (features / "permalinks.md").write_text("x", encoding="utf-8")
            self.assertEqual(
                save_plan._parent_path(root, "permalinks"),
                "features/permalinks.md",
            )

    def test_parent_is_blank_when_it_resolves_to_nothing(self) -> None:
        """A dangling link is worse than no link -- `canon_plan` and
        `canon_position` both follow this field."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(save_plan._parent_path(Path(tmp), "nope.md"))


class MissingSectionAskTests(unittest.TestCase):
    """§06: "Missing -> it asks, once. It never rejects a plan."

    The recording half already worked (a `notes:` line in the header);
    the asking half emitted nothing, so nobody was ever told -- while
    `canon_ship` blocked on that same note. See
    docs/decisions/0002-ship-blocks-on-a-missing-required-section.md.
    """

    def _approve(self, root: Path, body: str) -> str:
        return _invoke_main(_approved_payload(root, body))

    def test_missing_non_goals_is_surfaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            message = self._approve(root, "## Verification\njust test\n")
            self.assertIn("## Non-goals", message)
            self.assertIn("scope check", message)

    def test_missing_verification_is_surfaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            message = self._approve(root, "## Non-goals\nNot the parser.\n")
            self.assertIn("## Verification", message)

    def test_both_missing_are_named_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            message = self._approve(root, "## Approach\nDo it.\n")
            self.assertIn("## Non-goals", message)
            self.assertIn("## Verification", message)

    def test_the_plan_is_saved_anyway(self) -> None:
        """It never rejects a plan."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            self._approve(root, "## Approach\nDo it.\n")
            saved = root / ".canon" / "plans" / "feature" / "widget.md"
            self.assertTrue(saved.exists())
            self.assertIn("## Approach", saved.read_text(encoding="utf-8"))

    def test_a_complete_plan_says_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            message = self._approve(
                root,
                "## Non-goals\nNot the parser.\n\n## Verification\njust test\n",
            )
            self.assertEqual(message, "")

    def test_a_feature_plan_is_exempt(self) -> None:
        """`## Verification` has no meaning for a document that
        describes no branch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "main")
            message = self._approve(
                root, "# Permalinks\n\n## Steps\n- slugs: do the slugs\n"
            )
            self.assertEqual(message, "")


class VerifyOverrideTests(unittest.TestCase):
    def test_a_lone_backticked_first_line_is_an_override(self) -> None:
        section = "`pytest tests/slugs/ -x`\n\nConfirm it fails without the fix."
        self.assertEqual(save_plan._verify_override(section), "pytest tests/slugs/ -x")

    def test_prose_is_not_an_override(self) -> None:
        """Guessing a command out of a sentence is exactly the
        wrong-but-plausible failure §07's rule exists to prevent."""
        self.assertIsNone(save_plan._verify_override("1. Run the tests."))

    def test_a_bare_command_line_is_not_an_override(self) -> None:
        self.assertIsNone(save_plan._verify_override("just test"))

    def test_backticks_later_in_the_section_do_not_count(self) -> None:
        self.assertIsNone(save_plan._verify_override("Run the suite:\n\n`just test`"))

    def test_empty_section_is_no_override(self) -> None:
        self.assertIsNone(save_plan._verify_override(""))

    def test_override_reaches_the_saved_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/widget")
            body = (
                "## Non-goals\nDo not rewrite the parser.\n\n"
                "## Verification\n`pytest tests/slugs/ -x`\n"
            )
            _invoke_main(_approved_payload(root, body))
            header = _common.parse_header(
                (root / ".canon" / "plans" / "feature" / "widget.md").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(header["verify"], "pytest tests/slugs/ -x")


class DerivedHeaderEndToEndTests(unittest.TestCase):
    def test_a_plan_with_all_three_sections_populates_the_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/slugs")
            features = root / ".canon" / "plans" / "features"
            features.mkdir(parents=True, exist_ok=True)
            (features / "permalinks.md").write_text("x", encoding="utf-8")
            body = (
                "## Scope\n- src/slugs/**\n- tests/slugs/**\n\n"
                "## Done\nduplicate slugs raise, with a regression test\n\n"
                "## Parent\npermalinks.md\n\n"
                "## Non-goals\nDo not rewrite the parser.\n\n"
                "## Verification\njust test\n"
            )
            _invoke_main(_approved_payload(root, body))

            header = _common.parse_header(
                (root / ".canon" / "plans" / "feature" / "slugs.md").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(header["scope"], "[src/slugs/**, tests/slugs/**]")
            self.assertEqual(
                header["done"], "duplicate slugs raise, with a regression test"
            )
            self.assertEqual(header["parent"], "features/permalinks.md")
            self.assertNotIn("notes", header)

    def test_a_plan_with_none_of_them_leaves_all_three_blank(self) -> None:
        """Derived, not demanded -- §06's rule is unchanged by this."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, "feature/slugs")
            body = (
                "## Approach\nDo the thing.\n\n"
                "## Non-goals\nDo not rewrite the parser.\n\n"
                "## Verification\njust test\n"
            )
            _invoke_main(_approved_payload(root, body))

            header = _common.parse_header(
                (root / ".canon" / "plans" / "feature" / "slugs.md").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(header["scope"], "")
            self.assertEqual(header["done"], "")
            self.assertEqual(header["parent"], "")


if __name__ == "__main__":
    unittest.main()
