# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/skills/."""

from __future__ import annotations

import re
import unittest

from tests.antigravity.conftest import AGY_SKILLS_DIR

EXPECTED_SKILLS = [
    "frame",
    "plan",
    "review-change",
    "decide",
    "ship",
    "testing-craft",
    "reviewer",
    "risk-reviewer",
    "review",
]

_FRONTMATTER_PATTERN = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def _parse_yaml_frontmatter(content: str) -> dict[str, str]:
    match = _FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}
    raw = match.group(1)
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


class SkillsExistenceTests(unittest.TestCase):
    def test_all_nine_skills_present(self) -> None:
        self.assertEqual(len(EXPECTED_SKILLS), 9)
        self.assertTrue(AGY_SKILLS_DIR.is_dir())
        for skill_name in EXPECTED_SKILLS:
            skill_file = AGY_SKILLS_DIR / skill_name / "SKILL.md"
            self.assertTrue(
                skill_file.is_file(),
                f"Skill file {skill_file} must exist for skill '{skill_name}'",
            )


class SkillsFrontmatterTests(unittest.TestCase):
    def test_valid_yaml_frontmatter_in_all_skills(self) -> None:
        for skill_name in EXPECTED_SKILLS:
            skill_file = AGY_SKILLS_DIR / skill_name / "SKILL.md"
            content = skill_file.read_text(encoding="utf-8")
            self.assertTrue(
                content.startswith("---\n") or content.startswith("---\r\n"),
                f"Skill {skill_name} must begin with frontmatter marker '---'",
            )
            fm = _parse_yaml_frontmatter(content)
            self.assertIn(
                "name", fm, f"Skill {skill_name} missing 'name' in frontmatter"
            )
            self.assertEqual(
                fm["name"],
                skill_name,
                f"Skill {skill_name} frontmatter 'name' must match folder name",
            )
            self.assertIn(
                "description",
                fm,
                f"Skill {skill_name} missing 'description' in frontmatter",
            )
            self.assertTrue(
                len(fm["description"]) > 10,
                f"Skill {skill_name} description must be non-empty and descriptive",
            )


class SkillsToolMappingTests(unittest.TestCase):
    def test_tool_primitives_mapped_to_antigravity(self) -> None:
        remaps_found = set()
        for skill_name in EXPECTED_SKILLS:
            skill_file = AGY_SKILLS_DIR / skill_name / "SKILL.md"
            content = skill_file.read_text(encoding="utf-8")
            for agy_tool in (
                "run_command",
                "replace_file_content",
                "write_to_file",
                "view_file",
                "grep_search",
                "find_by_name",
            ):
                if agy_tool in content:
                    remaps_found.add(agy_tool)

        # Confirm all 6 core Antigravity tools are mentioned across skills
        self.assertEqual(
            remaps_found,
            {
                "run_command",
                "replace_file_content",
                "write_to_file",
                "view_file",
                "grep_search",
                "find_by_name",
            },
        )

    def test_no_legacy_claude_tool_invocations(self) -> None:
        legacy_patterns = [
            re.compile(r"\bUse the `?Bash`? tool\b", re.IGNORECASE),
            re.compile(r"\bUse the `?Edit`? tool\b", re.IGNORECASE),
            re.compile(r"\bUse the `?Write`? tool\b", re.IGNORECASE),
            re.compile(r"\bUse the `?Read`? tool\b", re.IGNORECASE),
            re.compile(r"\bUse the `?Grep`? tool\b", re.IGNORECASE),
            re.compile(r"\bUse the `?Glob`? tool\b", re.IGNORECASE),
        ]
        for skill_name in EXPECTED_SKILLS:
            skill_file = AGY_SKILLS_DIR / skill_name / "SKILL.md"
            content = skill_file.read_text(encoding="utf-8")
            for pat in legacy_patterns:
                self.assertIsNone(
                    pat.search(content),
                    f"Skill {skill_name} contains legacy Claude tool instruction: "
                    f"{pat.pattern}",
                )


class ReviewSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_file = AGY_SKILLS_DIR / "review" / "SKILL.md"
        self.assertTrue(self.skill_file.is_file())
        self.content = self.skill_file.read_text(encoding="utf-8")
        self.fm = _parse_yaml_frontmatter(self.content)

    def test_review_frontmatter(self) -> None:
        self.assertEqual(self.fm.get("name"), "review")
        self.assertIn("review", self.fm.get("description", "").lower())
        self.assertTrue(len(self.fm.get("description", "")) > 10)

    def test_review_queries_canon_review(self) -> None:
        self.assertIn("canon_review", self.content)
        self.assertIn("reviewers_called_for", self.content)

    def test_review_dispatches_independent_reviewers(self) -> None:
        self.assertIn("reviewer", self.content)
        self.assertIn("risk-reviewer", self.content)
        self.assertIn("base..HEAD", self.content)

    def test_review_delta_aware_guidance(self) -> None:
        # Re-reviewers must inspect delta in addition to full range
        self.assertIn("stale", self.content)
        self.assertIn("delta", self.content.lower())
        self.assertIn("verdicts[<name>].stale", self.content)
        self.assertTrue(
            "<previous_head>..HEAD" in self.content or "<head>..HEAD" in self.content
        )

    def test_review_two_round_grinding_cap(self) -> None:
        # Two-round grinding cap before consulting human developer
        self.assertIn("CHANGES REQUIRED", self.content)
        self.assertTrue(
            "two" in self.content.lower() or "second" in self.content.lower()
        )
        self.assertTrue(
            "ask the developer" in self.content.lower()
            or "consulting the human" in self.content.lower()
        )

    def test_review_uses_antigravity_tools(self) -> None:
        tools = (
            "run_command",
            "view_file",
            "replace_file_content",
            "write_to_file",
        )
        for tool in tools:
            self.assertIn(tool, self.content)


class FrameSkillDependencyNotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_file = AGY_SKILLS_DIR / "frame" / "SKILL.md"
        self.assertTrue(self.skill_file.is_file())
        self.content = self.skill_file.read_text(encoding="utf-8")

    def test_frame_contains_after_dependency_notation(self) -> None:
        self.assertIn("(after: ...)", self.content)
        self.assertIn("(after: none)", self.content)
        self.assertIn("canon_position", self.content)


class ReviewChangeSkillDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill_file = AGY_SKILLS_DIR / "review-change" / "SKILL.md"
        self.assertTrue(self.skill_file.is_file())
        self.content = self.skill_file.read_text(encoding="utf-8")
        self.fm = _parse_yaml_frontmatter(self.content)

    def test_review_change_indicates_dispatch_via_review_skill(self) -> None:
        desc = self.fm.get("description", "")
        self.assertIn("review", desc)
        self.assertIn("dispatch", desc.lower())
        # Body also mentions dispatch via review skill
        self.assertIn("review", self.content)
        self.assertIn("dispatch", self.content.lower())


class ReviewerSkillsConstraintsTests(unittest.TestCase):
    def test_reviewer_read_only_constraints(self) -> None:
        for reviewer_name in ("reviewer", "risk-reviewer"):
            skill_file = AGY_SKILLS_DIR / reviewer_name / "SKILL.md"
            content = skill_file.read_text(encoding="utf-8")
            self.assertIn("read-only", content.lower())
            self.assertIn("NEVER", content)
            self.assertIn("replace_file_content", content)
            self.assertIn("write_to_file", content)
            self.assertIn("Do not modify code", content)


if __name__ == "__main__":
    unittest.main()
