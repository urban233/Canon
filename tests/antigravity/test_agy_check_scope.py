# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/hooks/check_scope.py."""

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

agy_check_scope = load_agy_module("check_scope")
agy_config = load_agy_module("_config")
agy_common = load_agy_module("_common_agy")


class CheckScopeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "conv-scope-contract"
        self.state_dir = self.artifacts / self.conv_id / "canon"
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_always_emits_empty_dict(self) -> None:
        # Check that empty payload, error payload, and normal payload all emit {}
        for payload in (
            {},
            {"error": "Some tool execution failure"},
            make_post_tool_payload(
                "replace_file_content", {"TargetFile": "foo.py"}, workspace=self.repo
            ),
        ):
            parsed, _, _ = invoke_hook_main(agy_check_scope, payload=payload)
            self.assertEqual(parsed, {})


class CheckScopeEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "conv-scope-eval"
        self.state_dir = self.artifacts / self.conv_id / "canon"
        agy_config.save_config(self.repo, {"verify": "pytest"})

        # Setup branch and plan
        subprocess.run(
            ["git", "checkout", "-b", "feat-scope"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        plan_content = (
            "---\n"
            "status: approved\n"
            "scope: [src/**, tests/**]\n"
            "---\n\n"
            "# Feature Plan\n\n"
            "## Scope\n[src/**, tests/**]\n\n"
            "## Non-goals\n* Do not touch auth.py or docs\n"
        )
        plan_file = self.repo / ".canon" / "plans" / "feat-scope.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(plan_content, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_file_within_scope_patterns_resets_counter(self) -> None:
        # Pre-set counter to 2
        counter_file = self.state_dir / "consecutive_scope_departures"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        counter_file.write_text("2")

        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "src" / "worker.py")},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_check_scope, payload=payload)
        self.assertEqual(parsed, {})
        self.assertEqual(counter_file.read_text().strip(), "0")
        self.assertFalse((self.state_dir / "last_scope_departure").exists())

    def test_file_outside_scope_increments_counter(self) -> None:
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "scripts" / "deploy.sh")},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )

        # 1st departure
        invoke_hook_main(agy_check_scope, payload=payload)
        self.assertEqual(
            (self.state_dir / "consecutive_scope_departures").read_text().strip(), "1"
        )
        last = (self.state_dir / "last_scope_departure").read_text()
        self.assertIn("outside the plan's declared scope", last)

        # 2nd departure
        invoke_hook_main(agy_check_scope, payload=payload)
        self.assertEqual(
            (self.state_dir / "consecutive_scope_departures").read_text().strip(), "2"
        )

    def test_sustained_departures_logs_decision(self) -> None:
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "scripts" / "deploy.sh")},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        # Trigger 3 departures
        for _ in range(3):
            invoke_hook_main(agy_check_scope, payload=payload)

        self.assertEqual(
            (self.state_dir / "consecutive_scope_departures").read_text().strip(), "3"
        )
        rec = agy_common.last_decision(self.repo, "check_scope.py")
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["decision"], "departure")
        self.assertEqual(rec["consecutive"], 3)
        self.assertEqual(rec["file"], "scripts/deploy.sh")

    def test_file_in_non_goals_is_flagged(self) -> None:
        # src/auth.py matches scope glob src/** BUT is explicitly named in ## Non-goals
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "src" / "auth.py")},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        invoke_hook_main(agy_check_scope, payload=payload)
        self.assertEqual(
            (self.state_dir / "consecutive_scope_departures").read_text().strip(), "1"
        )
        last = (self.state_dir / "last_scope_departure").read_text()
        self.assertIn("named in the plan's ## Non-goals", last)


class CheckScopeExemptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "conv-scope-exempt"
        self.state_dir = self.artifacts / self.conv_id / "canon"
        agy_config.save_config(self.repo, {"verify": "pytest"})

        subprocess.run(
            ["git", "checkout", "-b", "feat-exempt"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        plan_content = (
            "---\nstatus: approved\nscope: [src/**]\n---\n\n## Scope\n[src/**]\n"
        )
        plan_file = self.repo / ".canon" / "plans" / "feat-exempt.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(plan_content, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_canon_metadata_is_exempt(self) -> None:
        for exempt_file in (
            ".canon/config.json",
            ".canon/plans/feat-exempt.md",
            ".canon/hooks/decisions.jsonl",
        ):
            payload = make_post_tool_payload(
                "write_to_file",
                {"TargetFile": str(self.repo / exempt_file)},
                workspace=self.repo,
                conversation_id=self.conv_id,
                artifact_dir=self.artifacts,
            )
            invoke_hook_main(agy_check_scope, payload=payload)
            # Counter should NOT be incremented
            counter = self.state_dir / "consecutive_scope_departures"
            self.assertFalse(counter.exists() and counter.read_text().strip() != "0")

    def test_unconfigured_repo_is_inert(self) -> None:
        # Remove verify from config
        (self.repo / ".canon" / "config.json").unlink()
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.repo / "scripts" / "outside.py")},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        invoke_hook_main(agy_check_scope, payload=payload)
        counter = self.state_dir / "consecutive_scope_departures"
        self.assertFalse(counter.exists())


if __name__ == "__main__":
    unittest.main()
