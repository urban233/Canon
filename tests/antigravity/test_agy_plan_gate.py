# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/hooks/plan_gate.py."""

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
    make_pre_tool_payload,
)

agy_plan_gate = load_agy_module("plan_gate")
agy_config = load_agy_module("_config")
agy_common = load_agy_module("_common_agy")


class PlanGateInertBypassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_unrecognized_tool_allowed(self) -> None:
        agy_config.save_config(self.repo, {"verify": "pytest"})
        payload = make_pre_tool_payload(
            "view_file",
            {"AbsolutePath": "/path/to/file.py"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})

    def test_unconfigured_repo_allowed(self) -> None:
        # No config, or config without verification signal
        payload = make_pre_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "README.md")},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})

    def test_missing_workspace_allowed(self) -> None:
        payload = make_pre_tool_payload(
            "replace_file_content",
            {"TargetFile": "some_file.py"},
            workspace=None,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})


class PlanGateDefaultBranchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_blocks_edit_on_default_branch_in_solo_mode(self) -> None:
        # Standing on main (default branch)
        payload = make_pre_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "README.md")},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "ask")
        self.assertIn("default branch", parsed.get("reason", ""))
        self.assertIn("branch before editing", parsed.get("reason", ""))

    def test_blocks_write_to_file_on_default_branch(self) -> None:
        payload = make_pre_tool_payload(
            "write_to_file",
            {"TargetFile": str(self.repo / "new_file.py"), "CodeContent": "x = 1"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "ask")
        self.assertIn("default branch", parsed.get("reason", ""))

    def test_blocks_edit_on_default_branch_in_async_mode(self) -> None:
        agy_config.save_config(self.repo, {"verify": "pytest", "mode": "async"})
        payload = make_pre_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "README.md")},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "deny")
        self.assertIn("treat this as declined for now", parsed.get("reason", ""))

    def test_allows_edit_on_default_branch_when_guard_disabled(self) -> None:
        agy_config.save_config(
            self.repo, {"verify": "pytest", "guard_default_branch": False}
        )
        # Also need a plan for main if required, or check plan exists
        plan_file = self.repo / ".canon" / "plans" / "main.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text("# Plan for main\n")

        payload = make_pre_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "README.md")},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})


class PlanGateMissingPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})
        # Switch to feature branch
        subprocess.run(
            ["git", "checkout", "-b", "feat-test"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_blocks_edit_without_plan(self) -> None:
        payload = make_pre_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "src" / "code.py")},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "ask")
        self.assertIn(
            "No plan is saved for branch 'feat-test' yet", parsed.get("reason", "")
        )

    def test_allows_edit_with_plan(self) -> None:
        plan_dir = self.repo / ".canon" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "feat-test.md").write_text("# Plan\n", encoding="utf-8")

        payload = make_pre_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "src" / "code.py")},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})

    def test_bootstrapping_exemption_for_writing_plan(self) -> None:
        # On feat-test without existing plan, writing .canon/plans/feat-test.md
        # is allowed
        target = str(self.repo / ".canon" / "plans" / "feat-test.md")
        payload = make_pre_tool_payload(
            "write_to_file",
            {"TargetFile": target, "CodeContent": "# New Plan\n"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})

    def test_bootstrapping_exemption_still_guards_default_branch(self) -> None:
        # Switch back to main
        subprocess.run(
            ["git", "checkout", "main"], cwd=self.repo, check=True, capture_output=True
        )
        target = str(self.repo / ".canon" / "plans" / "main.md")
        payload = make_pre_tool_payload(
            "write_to_file",
            {"TargetFile": target, "CodeContent": "# New Plan\n"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "ask")
        self.assertIn("default branch", parsed.get("reason", ""))


class PlanGateGitCommandsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_allows_branching_from_default_branch(self) -> None:
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": "git checkout -b feature-1"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})

    def test_blocks_nesting_branch_when_already_on_feature_branch(self) -> None:
        subprocess.run(
            ["git", "checkout", "-b", "feature-1"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        for cmd in (
            "git checkout -b nested",
            "git switch -c nested",
            "git switch --create nested",
        ):
            payload = make_pre_tool_payload(
                "run_command",
                {"CommandLine": cmd},
                workspace=self.repo,
                artifact_dir=self.artifacts,
            )
            parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.get("decision"), "ask")
            self.assertIn("nesting a new branch under it", parsed.get("reason", ""))

    def test_blocks_committing_on_default_branch(self) -> None:
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": "git commit -m 'direct commit on main'"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "ask")
        self.assertIn(
            "default branch (main) -- branch before committing",
            parsed.get("reason", ""),
        )

    def test_allows_benign_commands(self) -> None:
        for cmd in ("git status", "git diff", "git log -n 5", "pytest", "ls -la"):
            payload = make_pre_tool_payload(
                "run_command",
                {"CommandLine": cmd},
                workspace=self.repo,
                artifact_dir=self.artifacts,
            )
            parsed, _, _ = invoke_hook_main(agy_plan_gate, payload=payload)
            self.assertEqual(parsed, {"decision": "allow"})


if __name__ == "__main__":
    unittest.main()
