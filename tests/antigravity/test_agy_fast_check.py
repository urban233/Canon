# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/hooks/fast_check.py."""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.antigravity.conftest import (
    create_test_git_repo,
    invoke_hook_main,
    load_agy_module,
    make_post_tool_payload,
)

agy_fast_check = load_agy_module("fast_check")
agy_config = load_agy_module("_config")
agy_common = load_agy_module("_common_agy")


class FastCheckInertPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-fc-inert"
        self.state_dir = self.artifacts / self.conv_id / "canon"

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_silent_without_verify(self) -> None:
        # check is set, but no verify: Canon is inert
        agy_config.save_config(self.repo, {"check": "echo checking"})
        target = self.repo / "src" / "foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")

        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertEqual(parsed, {})

    def test_silent_without_check(self) -> None:
        # verify is set, but no check: layer 1 inactive
        agy_config.save_config(self.repo, {"verify": "pytest"})
        target = self.repo / "src" / "foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")

        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertEqual(parsed, {})

    def test_silent_for_non_edit_tool(self) -> None:
        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo ok"})
        payload = make_post_tool_payload(
            "run_command",
            {"CommandLine": "ls -la"},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertEqual(parsed, {})

    def test_silent_when_no_file_path(self) -> None:
        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo ok"})
        payload = make_post_tool_payload(
            "replace_file_content",
            {},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertEqual(parsed, {})

    def test_silent_on_tool_error(self) -> None:
        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo ok"})
        target = self.repo / "src" / "foo.py"
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
            error="file not found",
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertEqual(parsed, {})


class FastCheckOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-fc-outcome"
        self.state_dir = self.artifacts / self.conv_id / "canon"
        self.target = self.repo / "src" / "foo.py"
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("x = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_passing_check_silent(self) -> None:
        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo passing"})
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertEqual(parsed, {})

    def test_failing_check_emits_context(self) -> None:
        agy_config.save_config(
            self.repo,
            {"verify": "pytest", "check": "python3 -c 'import sys; sys.exit(1)'"},
        )
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("additionalContext", parsed)
        self.assertIn(
            "Canon's fast check failed after this edit",
            parsed["additionalContext"],
        )
        # Invariant: Never blocks (no decision: deny/continue)
        self.assertNotIn("decision", parsed)

    def test_timeout_silent(self) -> None:
        agy_config.save_config(
            self.repo,
            {"verify": "pytest", "check": "python3 -c 'import time; time.sleep(10)'"},
        )
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        # Mock run_command to simulate timeout
        with patch.object(
            agy_common,
            "run_command",
            return_value=agy_common.CommandResult(
                exit_code=124, stdout="", stderr="timed out", timed_out=True
            ),
        ):
            parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertEqual(parsed, {})
        # Verify backoff stamp was recorded
        next_run = float((self.state_dir / "fast_check_next_run").read_text().strip())
        self.assertGreater(next_run, time.time() + 500)


class FastCheckConfigFaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-fc-fault"
        self.state_dir = self.artifacts / self.conv_id / "canon"
        self.target = self.repo / "src" / "foo.py"
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("x = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_compound_command_reported_as_fault(self) -> None:
        agy_config.save_config(
            self.repo,
            {"verify": "pytest", "check": "ruff check && flake8"},
        )
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("additionalContext", parsed)
        self.assertIn("cannot be run as configured", parsed["additionalContext"])
        self.assertIn("configuration problem", parsed["additionalContext"])

        # Second invocation in the same session is silent
        parsed2, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertEqual(parsed2, {})

    def test_missing_binary_reported_as_fault(self) -> None:
        agy_config.save_config(
            self.repo,
            {"verify": "pytest", "check": "nonexistent_binary_xyz_123_tool"},
        )
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("additionalContext", parsed)
        self.assertIn("cannot be run as configured", parsed["additionalContext"])


class FastCheckDebounceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-fc-debounce"
        self.state_dir = self.artifacts / self.conv_id / "canon"
        self.target = self.repo / "src" / "foo.py"
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("x = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_second_edit_in_window_debounced(self) -> None:
        call_count = 0

        def _mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return agy_common.CommandResult(exit_code=0, stdout="ok", stderr="")

        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo check"})
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )

        with patch.object(agy_common, "run_command", side_effect=_mock_run):
            # 1st edit: runs command
            parsed1, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
            self.assertEqual(call_count, 1)

            # 2nd edit immediately: debounced, does not run
            parsed2, _, _ = invoke_hook_main(agy_fast_check, payload=payload)
            self.assertEqual(call_count, 1)

    def test_runs_again_after_window_expires(self) -> None:
        call_count = 0

        def _mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return agy_common.CommandResult(exit_code=0, stdout="ok", stderr="")

        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo check"})
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )

        with patch.object(agy_common, "run_command", side_effect=_mock_run):
            invoke_hook_main(agy_fast_check, payload=payload)
            self.assertEqual(call_count, 1)

            # Set stamp to the past
            stamp_file = self.state_dir / "fast_check_next_run"
            stamp_file.write_text(str(time.time() - 10), encoding="utf-8")

            # Runs again
            invoke_hook_main(agy_fast_check, payload=payload)
            self.assertEqual(call_count, 2)

    def test_no_session_state_runs_every_time(self) -> None:
        call_count = 0

        def _mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return agy_common.CommandResult(exit_code=0, stdout="ok", stderr="")

        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo check"})
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=None,  # No session state
            artifact_dir=None,
        )

        with patch.object(agy_common, "run_command", side_effect=_mock_run):
            invoke_hook_main(agy_fast_check, payload=payload)
            invoke_hook_main(agy_fast_check, payload=payload)
            self.assertEqual(call_count, 2)


class FastCheckStandDownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-fc-standdown"
        self.state_dir = self.artifacts / self.conv_id / "canon"
        self.target = self.repo / "src" / "foo.py"
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("x = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_timeout_stands_down_long_window(self) -> None:
        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo slow"})
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )
        call_count = 0

        def _mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return agy_common.CommandResult(
                exit_code=124, stdout="", stderr="timed out", timed_out=True
            )

        with patch.object(agy_common, "run_command", side_effect=_mock_run):
            invoke_hook_main(agy_fast_check, payload=payload)
            self.assertEqual(call_count, 1)

            # Next check should be deferred due to 600s backoff
            invoke_hook_main(agy_fast_check, payload=payload)
            self.assertEqual(call_count, 1)

    def test_future_clock_skew_fails_toward_running(self) -> None:
        call_count = 0

        def _mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return agy_common.CommandResult(exit_code=0, stdout="ok", stderr="")

        agy_config.save_config(self.repo, {"verify": "pytest", "check": "echo check"})
        payload = make_post_tool_payload(
            "replace_file_content",
            {"TargetFile": str(self.target)},
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts,
        )

        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Put timestamp 10,000s in the future (implausible clock skew)
        skew_target = self.state_dir / "fast_check_next_run"
        skew_target.write_text(str(time.time() + 10000), encoding="utf-8")

        with patch.object(agy_common, "run_command", side_effect=_mock_run):
            invoke_hook_main(agy_fast_check, payload=payload)
            self.assertEqual(call_count, 1)


if __name__ == "__main__":
    unittest.main()
