# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/hooks/session_context.py."""

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
    make_pre_invocation_payload,
)

agy_session_context = load_agy_module("session_context")
agy_config = load_agy_module("_config")
agy_common = load_agy_module("_common_agy")


class SessionContextTurnGatingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_turn_zero_injects_context(self) -> None:
        payload = make_pre_invocation_payload(
            invocation_num=0,
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("injectSteps", parsed)
        steps = parsed["injectSteps"]
        self.assertEqual(len(steps), 1)
        self.assertIn("ephemeralMessage", steps[0])
        self.assertIn("Canon position: branch `main`", steps[0]["ephemeralMessage"])

    def test_subsequent_turns_silent(self) -> None:
        for turn in (1, 2, 5, 10):
            payload = make_pre_invocation_payload(
                invocation_num=turn,
                workspace=self.repo,
                artifact_dir=self.artifacts,
            )
            parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
            self.assertEqual(parsed, {})


class SessionContextCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_compact_source_injects_recap(self) -> None:
        payload = make_pre_invocation_payload(
            invocation_num=4,
            source="compact",
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("injectSteps", parsed)
        msg = parsed["injectSteps"][0]["ephemeralMessage"]
        self.assertIn("Canon position: branch `main`", msg)
        self.assertIn("Post-compaction recap", msg)
        self.assertIn("survives the summariser", msg)

    def test_is_compacted_flag_injects_recap(self) -> None:
        payload = make_pre_invocation_payload(
            invocation_num=2,
            is_compact=True,
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("injectSteps", parsed)
        msg = parsed["injectSteps"][0]["ephemeralMessage"]
        self.assertIn("Post-compaction recap", msg)


class SessionContextFailOpenBypassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_missing_payload_emits_empty(self) -> None:
        parsed, _, _ = invoke_hook_main(agy_session_context, raw_stdin="")
        self.assertEqual(parsed, {})

    def test_missing_workspace_paths_emits_empty(self) -> None:
        payload = {"invocationNum": 0, "artifactDirectoryPath": str(self.artifacts)}
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertEqual(parsed, {})

    def test_empty_workspace_paths_emits_empty(self) -> None:
        payload = make_pre_invocation_payload(
            invocation_num=0,
            workspace=None,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertEqual(parsed, {})

    def test_missing_artifact_dir_emits_empty(self) -> None:
        payload = {
            "invocationNum": 0,
            "workspacePaths": [str(self.repo)],
        }
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertEqual(parsed, {})

    def test_empty_artifact_dir_emits_empty(self) -> None:
        payload = make_pre_invocation_payload(
            invocation_num=0,
            workspace=self.repo,
            artifact_dir="",
        )
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertEqual(parsed, {})

    def test_nonexistent_repo_dir_emits_empty(self) -> None:
        payload = make_pre_invocation_payload(
            invocation_num=0,
            workspace="/nonexistent/path/never/real",
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertEqual(parsed, {})


class SessionContextPositionContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "just check"})

        subprocess.run(
            ["git", "checkout", "-b", "feat-billing"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        plan_content = (
            "---\n"
            "status: approved\n"
            'done: "Stripe integration complete"\n'
            "---\n\n"
            "# Billing Plan\n\n"
            "## Scope\n- `src/billing/**`\n\n"
            "## Non-goals\n* No crypto payments\n\n"
            "## Done\nStripe integration complete.\n"
        )
        plan_file = self.repo / ".canon" / "plans" / "feat-billing.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(plan_content, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_derives_branch_plan_verify_status(self) -> None:
        payload = make_pre_invocation_payload(
            invocation_num=0,
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        msg = parsed["injectSteps"][0]["ephemeralMessage"]
        self.assertIn("Canon position: branch `feat-billing`", msg)
        self.assertIn("Plan: approved (.canon/plans/feat-billing.md)", msg)
        self.assertIn("Done: Stripe integration complete", msg)
        self.assertIn("Verify: `just check`", msg)

    def test_detects_untracked_notebooks_warning(self) -> None:
        # Commit a notebook
        nb_file = self.repo / "analysis.ipynb"
        nb_file.write_text('{"cells": []}', encoding="utf-8")
        subprocess.run(
            ["git", "add", "analysis.ipynb"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add notebook"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

        payload = make_pre_invocation_payload(
            invocation_num=0,
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        msg = parsed["injectSteps"][0]["ephemeralMessage"]
        self.assertIn(
            "Notebooks: this repository tracks .ipynb files (e.g. analysis.ipynb)", msg
        )

        # Now configure .gitattributes
        (self.repo / ".gitattributes").write_text(
            "*.ipynb filter=nbstripout\n", encoding="utf-8"
        )
        parsed2, _, _ = invoke_hook_main(agy_session_context, payload=payload)
        self.assertIsNotNone(parsed2)
        assert parsed2 is not None
        msg2 = parsed2["injectSteps"][0]["ephemeralMessage"]
        self.assertNotIn("Notebooks: this repository tracks .ipynb files", msg2)


if __name__ == "__main__":
    unittest.main()
