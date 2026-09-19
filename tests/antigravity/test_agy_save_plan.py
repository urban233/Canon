# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/hooks/save_plan.py."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.antigravity.conftest import (
    create_test_git_repo,
    invoke_hook_main,
    load_agy_module,
    make_post_tool_payload,
)

agy_save_plan = load_agy_module("save_plan")
agy_config = load_agy_module("_config")
agy_common = load_agy_module("_common_agy")


class SavePlanFilteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_ignores_non_plan_files(self) -> None:
        src_file = self.repo / "src" / "index.py"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_text("print('hello')", encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(src_file), "CodeContent": "print('hello')"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_save_plan, payload=payload)
        self.assertEqual(parsed, {})
        # File untouched
        self.assertEqual(src_file.read_text(), "print('hello')")

    def test_ignores_non_markdown_in_plans_dir(self) -> None:
        json_file = self.repo / ".canon" / "plans" / "data.json"
        json_file.parent.mkdir(parents=True, exist_ok=True)
        json_file.write_text('{"key": "value"}', encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(json_file), "CodeContent": '{"key": "value"}'},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_save_plan, payload=payload)
        self.assertEqual(parsed, {})
        self.assertEqual(json_file.read_text(), '{"key": "value"}')


class SavePlanHeaderDerivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest -v"})
        subprocess.run(
            ["git", "checkout", "-b", "feat-add-auth"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_derives_branch_plan_headers(self) -> None:
        plan_path = self.repo / ".canon" / "plans" / "feat-add-auth.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        raw_content = (
            "# Plan: Add Authentication\n\n"
            "## Scope\n- `src/auth/**`\n- `tests/test_auth.py`\n\n"
            "## Non-goals\n* Do not touch billing\n\n"
            "## Done\nUser login and session validation working.\n\n"
            "## Verification\n`pytest tests/test_auth.py`\n"
        )
        plan_path.write_text(raw_content, encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(plan_path), "CodeContent": raw_content},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_save_plan, payload=payload)
        self.assertEqual(parsed, {})

        # Verify disk file was rewritten with frontmatter
        saved_text = plan_path.read_text(encoding="utf-8")
        self.assertTrue(saved_text.startswith("---\n"))
        header, body = agy_common.plan_header_and_body(saved_text)
        self.assertEqual(header.get("status"), "approved")
        self.assertIsNotNone(header.get("base"))
        self.assertEqual(header.get("scope"), "[src/auth/**, tests/test_auth.py]")
        self.assertEqual(
            header.get("done"), "User login and session validation working"
        )
        self.assertIn("pytest", header.get("verify", ""))
        self.assertNotIn("notes", header)  # Non-goals and Verification were present

        # Decision logged
        rec = agy_common.last_decision(self.repo, "save_plan.py")
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["decision"], "saved")

    def test_notes_missing_required_sections(self) -> None:
        plan_path = self.repo / ".canon" / "plans" / "feat-add-auth.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        # Missing ## Non-goals and ## Verification
        raw_content = (
            "# Plan: Incomplete Plan\n\n## Scope\n[src/**]\n\n## Done\nDone done.\n"
        )
        plan_path.write_text(raw_content, encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(plan_path), "CodeContent": raw_content},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        invoke_hook_main(agy_save_plan, payload=payload)

        header, _ = agy_common.plan_header_and_body(
            plan_path.read_text(encoding="utf-8")
        )
        notes = header.get("notes", "")
        self.assertIn("Non-goals section is missing or empty", notes)
        self.assertIn("Verification section is missing or empty", notes)

    def test_derives_feature_plan_headers(self) -> None:
        # Writing to features/ directory
        feature_path = self.repo / ".canon" / "plans" / "features" / "new-ui.md"
        feature_path.parent.mkdir(parents=True, exist_ok=True)
        raw_content = (
            "# Feature: New UI\n\n"
            "## Steps\n"
            "- Step 1: Mock components\n"
            "- Step 2: Implement styling\n"
        )
        feature_path.write_text(raw_content, encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(feature_path), "CodeContent": raw_content},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_save_plan, payload=payload)
        self.assertEqual(parsed, {})

        header, body = agy_common.plan_header_and_body(
            feature_path.read_text(encoding="utf-8")
        )
        self.assertEqual(header.get("status"), "approved")
        self.assertIn("steps", header)

    def test_preserves_explicit_custom_frontmatter_fields(self) -> None:
        plan_path = self.repo / ".canon" / "plans" / "feat-add-auth.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        raw_content = (
            "---\n"
            'verify: "custom-verify-cmd --fast"\n'
            'parent: "feat-base-branch"\n'
            "---\n\n"
            "# Plan\n\n"
            "## Scope\n[src/**]\n\n"
            "## Non-goals\nNone.\n\n"
            "## Done\nFinished.\n\n"
            "## Verification\nPasses.\n"
        )
        plan_path.write_text(raw_content, encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(plan_path), "CodeContent": raw_content},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        invoke_hook_main(agy_save_plan, payload=payload)

        header, _ = agy_common.plan_header_and_body(
            plan_path.read_text(encoding="utf-8")
        )
        self.assertEqual(header.get("verify"), "custom-verify-cmd --fast")
        self.assertEqual(header.get("parent"), "feat-base-branch")


class SavePlanLegacyExitPlanModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})
        subprocess.run(
            ["git", "checkout", "-b", "feat-legacy"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_handles_legacy_tool_response_exit_plan_mode(self) -> None:
        tool_resp = (
            "Plan approved!\n\n"
            "## Approved Plan:\n"
            "# Branch Plan\n\n"
            "## Scope\n[src/**]\n\n"
            "## Non-goals\nNone.\n\n"
            "## Done\nDone.\n\n"
            "## Verification\nPass.\n"
        )
        payload = make_post_tool_payload(
            "ExitPlanMode",
            {},
            workspace=self.repo,
            artifact_dir=self.artifacts,
            tool_response=tool_resp,
        )
        parsed, _, _ = invoke_hook_main(agy_save_plan, payload=payload)
        self.assertEqual(parsed, {})

        plan_path = self.repo / ".canon" / "plans" / "feat-legacy.md"
        self.assertTrue(plan_path.exists())
        header, _ = agy_common.plan_header_and_body(
            plan_path.read_text(encoding="utf-8")
        )
        self.assertEqual(header.get("status"), "approved")


class SavePlanCollisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_features_branch_plan_redirected_to_branches_dir(self) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "features/auth"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        plan_path = self.repo / ".canon" / "plans" / "features" / "auth.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        raw_content = (
            "# Plan: Branch Auth\n\n"
            "## Scope\n- `src/auth.py`\n\n"
            "## Non-goals\nNone.\n\n"
            "## Done\nAuth done.\n\n"
            "## Verification\n`pytest`\n"
        )
        plan_path.write_text(raw_content, encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(plan_path), "CodeContent": raw_content},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_save_plan, payload=payload)
        self.assertEqual(parsed, {})

        # Original path under features/ was moved!
        self.assertFalse(plan_path.exists())

        # Destination under branches/features/auth.md exists
        redirected_path = (
            self.repo / ".canon" / "plans" / "branches" / "features" / "auth.md"
        )
        self.assertTrue(redirected_path.exists())
        header, _ = agy_common.plan_header_and_body(
            redirected_path.read_text(encoding="utf-8")
        )
        self.assertEqual(header.get("status"), "approved")
        self.assertEqual(header.get("scope"), "[src/auth.py]")

        # Decision logged
        rec = agy_common.last_decision(self.repo, "save_plan.py")
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["decision"], "redirected")

    def test_case_insensitive_features_branch_redirect(self) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "Features/payment"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        plan_path = self.repo / ".canon" / "plans" / "features" / "payment.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        raw_content = (
            "# Plan: Payment\n\n"
            "## Scope\n- `src/pay.py`\n\n"
            "## Non-goals\nNone.\n\n"
            "## Done\nPayment done.\n\n"
            "## Verification\n`pytest`\n"
        )
        plan_path.write_text(raw_content, encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(plan_path), "CodeContent": raw_content},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_save_plan, payload=payload)
        self.assertEqual(parsed, {})

        # Original path was moved
        self.assertFalse(plan_path.exists())
        redirected_path = (
            self.repo / ".canon" / "plans" / "branches" / "Features" / "payment.md"
        )
        self.assertTrue(redirected_path.exists())

    def test_true_feature_plan_with_steps_not_redirected(self) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "features/auth"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        plan_path = self.repo / ".canon" / "plans" / "features" / "auth.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        raw_content = (
            "# Feature: Multi-step Auth\n\n"
            "## Steps\n"
            "- step 1: data model\n"
            "- step 2: controller\n"
        )
        plan_path.write_text(raw_content, encoding="utf-8")

        payload = make_post_tool_payload(
            "write_to_file",
            {"TargetFile": str(plan_path), "CodeContent": raw_content},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_save_plan, payload=payload)
        self.assertEqual(parsed, {})

        # Feature plan stays in place
        self.assertTrue(plan_path.exists())
        header, _ = agy_common.plan_header_and_body(
            plan_path.read_text(encoding="utf-8")
        )
        self.assertEqual(header.get("status"), "approved")
        self.assertIn("steps", header)


if __name__ == "__main__":
    unittest.main()
