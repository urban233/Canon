# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/hooks/stop.py."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tests.antigravity.conftest import (
    create_test_git_repo,
    invoke_hook_main,
    load_agy_module,
    make_stop_payload,
)

agy_stop = load_agy_module("stop")
agy_config = load_agy_module("_config")
agy_common = load_agy_module("_common_agy")


class StopFailOpenBypassTests(unittest.TestCase):
    def test_empty_payload_emits_empty(self) -> None:
        parsed, out, err = invoke_hook_main(agy_stop, raw_stdin="")
        self.assertEqual(parsed, {})

    def test_missing_workspace_paths_emits_empty(self) -> None:
        payload = {"conversationId": "c1", "artifactDirectoryPath": "/tmp"}
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed, {})

    def test_empty_workspace_paths_emits_empty(self) -> None:
        payload = make_stop_payload(
            workspace=None, conversation_id="c1", artifact_dir="/tmp"
        )
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed, {})

    def test_missing_artifact_dir_emits_empty(self) -> None:
        payload = {"workspacePaths": ["/tmp"], "conversationId": "c1"}
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed, {})

    def test_missing_conversation_id_emits_empty(self) -> None:
        payload = {"workspacePaths": ["/tmp"], "artifactDirectoryPath": "/tmp"}
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed, {})

    def test_nonexistent_repo_dir_emits_empty(self) -> None:
        payload = make_stop_payload(
            workspace="/nonexistent/path/never/real",
            conversation_id="c1",
            artifact_dir="/tmp",
        )
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed, {})


class StopFirstRunPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts_dir = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-first-run"
        self.state_dir = self.artifacts_dir / self.conv_id / "canon"

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts_dir, ignore_errors=True)

    def test_unconfigured_with_inferred_command(self) -> None:
        # Create a Justfile with test recipe
        (self.repo / "Justfile").write_text("test:\n\tcargo test\n", encoding="utf-8")
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "continue")
        self.assertIn("just test", parsed.get("reason", ""))
        # Verify prompted marker was created in scratchpad
        self.assertTrue((self.state_dir / "verify_prompted").exists())

        # Second invocation in the same session emits {}
        parsed2, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed2, {})

    def test_unconfigured_without_inference(self) -> None:
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "continue")
        self.assertIn("Nothing could be inferred", parsed.get("reason", ""))
        self.assertTrue((self.state_dir / "verify_prompted").exists())

        # Second invocation emits {}
        parsed2, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed2, {})


class StopConfiguredVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts_dir = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-configured"
        self.state_dir = self.artifacts_dir / self.conv_id / "canon"

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts_dir, ignore_errors=True)

    def test_verification_passes(self) -> None:
        agy_config.save_config(self.repo, {"verify": "echo all tests passed"})
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed, {})

        # Counter should be 0 in scratchpad
        refusal_counter_file = self.state_dir / "consecutive_refusals"
        if refusal_counter_file.exists():
            self.assertEqual(refusal_counter_file.read_text().strip(), "0")

        # Logged allow decision in repo
        rec = agy_common.last_decision(self.repo, "stop.py")
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["decision"], "allow")

    def test_verification_fails_and_increments_refusals(self) -> None:
        # Command that fails with exit code 42
        agy_config.save_config(
            self.repo,
            {"verify": "python3 -c 'import sys; sys.exit(42)'"},
        )
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )

        # 1st failure
        parsed1, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertIsNotNone(parsed1)
        assert parsed1 is not None
        self.assertEqual(parsed1.get("decision"), "continue")
        self.assertIn("exited 42", parsed1.get("reason", ""))
        self.assertEqual(
            (self.state_dir / "consecutive_refusals").read_text().strip(), "1"
        )

        # 2nd failure
        parsed2, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed2.get("decision"), "continue")
        self.assertEqual(
            (self.state_dir / "consecutive_refusals").read_text().strip(), "2"
        )

        # 3rd failure
        parsed3, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed3.get("decision"), "continue")
        self.assertEqual(
            (self.state_dir / "consecutive_refusals").read_text().strip(), "3"
        )

        # 4th failure: gives up! (cap is 3)
        parsed4, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed4, {})
        # Counter reset to 0
        self.assertEqual(
            (self.state_dir / "consecutive_refusals").read_text().strip(), "0"
        )

        # Verify decision log has the give-up reason
        rec = agy_common.last_decision(self.repo, "stop.py")
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["decision"], "allow")
        self.assertIn("giving up after 4 consecutive failures", rec["reason"])

    def test_passing_verification_resets_consecutive_refusals(self) -> None:
        agy_config.save_config(
            self.repo,
            {"verify": "python3 -c 'import sys; sys.exit(1)'"},
        )
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )

        # Fail once
        invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(
            (self.state_dir / "consecutive_refusals").read_text().strip(), "1"
        )

        # Now configure passing command
        agy_config.save_config(self.repo, {"verify": "echo ok"})
        parsed, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed, {})
        self.assertEqual(
            (self.state_dir / "consecutive_refusals").read_text().strip(), "0"
        )


class StopSafetyAndEdgeCasesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts_dir = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-safety"
        self.state_dir = self.artifacts_dir / self.conv_id / "canon"

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts_dir, ignore_errors=True)

    def test_state_strictly_in_scratchpad(self) -> None:
        agy_config.save_config(
            self.repo,
            {"verify": "python3 -c 'import sys; sys.exit(1)'"},
        )
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        invoke_hook_main(agy_stop, payload=payload)

        # Confirm no consecutive_refusals file in repo
        self.assertFalse((self.repo / "consecutive_refusals").exists())
        self.assertFalse((self.repo / ".canon" / "consecutive_refusals").exists())
        self.assertTrue((self.state_dir / "consecutive_refusals").exists())

    def test_unparseable_command_fails_gracefully(self) -> None:
        agy_config.save_config(self.repo, {"verify": 'echo "unclosed quote'})
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        parsed, out, err = invoke_hook_main(agy_stop, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "continue")
        self.assertIn("Could not parse", parsed.get("reason", ""))


class StopCompoundCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts_dir = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        self.conv_id = "test-conv-compound"
        self.state_dir = self.artifacts_dir / self.conv_id / "canon"

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts_dir, ignore_errors=True)

    def test_detects_compound_verify_command(self) -> None:
        agy_config.save_config(self.repo, {"verify": "make test && make lint"})
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        parsed, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "continue")
        self.assertIn("contains `&&`", parsed.get("reason", ""))
        self.assertIn("configuration problem", parsed.get("reason", ""))

    def test_compound_command_not_counted_against_refusals(self) -> None:
        agy_config.save_config(self.repo, {"verify": "make test && make lint"})
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        invoke_hook_main(agy_stop, payload=payload)
        refusal_counter = self.state_dir / "consecutive_refusals"
        if refusal_counter.exists():
            self.assertEqual(refusal_counter.read_text().strip(), "0")

    def test_compound_command_reported_once_per_session(self) -> None:
        agy_config.save_config(self.repo, {"verify": "pytest; ruff"})
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        parsed1, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertIsNotNone(parsed1)
        assert parsed1 is not None
        self.assertEqual(parsed1.get("decision"), "continue")
        self.assertIn("contains `;`", parsed1.get("reason", ""))

        # Second invocation in the same session allows stopping
        parsed2, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed2, {})

    def test_missing_binary_treated_as_config_fault_without_refusal_burn(self) -> None:
        agy_config.save_config(self.repo, {"verify": "nonexistent_verify_cmd_xyz"})
        payload = make_stop_payload(
            workspace=self.repo,
            conversation_id=self.conv_id,
            artifact_dir=self.artifacts_dir,
        )
        parsed1, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertIsNotNone(parsed1)
        assert parsed1 is not None
        self.assertEqual(parsed1.get("decision"), "continue")
        self.assertIn("configuration problem", parsed1.get("reason", ""))

        refusal_counter = self.state_dir / "consecutive_refusals"
        if refusal_counter.exists():
            self.assertEqual(refusal_counter.read_text().strip(), "0")

        # Second run allows stopping
        parsed2, _, _ = invoke_hook_main(agy_stop, payload=payload)
        self.assertEqual(parsed2, {})


if __name__ == "__main__":
    unittest.main()
