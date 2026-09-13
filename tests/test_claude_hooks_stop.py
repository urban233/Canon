# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/stop.py.

Covers the first-run question (asked once per session, via a real
block), the consecutive-refusal counter and its cap, and running the
configured verify command -- the properties Step 3's plan calls out as
non-negotiable for this hook.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import _common
import stop


def _invoke_main(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Run `stop.main()` against a synthetic payload.

    Returns the parsed JSON it emitted, or None for a silent `allow()`.
    Mirrors test_claude_hooks_common.py's `_captured_json` helper, since
    `stop.main()` ends in exactly one of `_common`'s output shapes.
    """
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with redirect_stdout(buffer):
            with mock.patch("sys.exit") as exit_mock:
                stop.main()
    exit_mock.assert_called_once_with(0)
    raw = buffer.getvalue()
    return json.loads(raw) if raw else None


class FirstRunTests(unittest.TestCase):
    def test_blocks_with_an_inferred_suggestion(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as scratch,
        ):
            (Path(root) / "Justfile").write_text(
                "test *args:\n    bazel test //tests/...\n", encoding="utf-8"
            )
            result = _invoke_main({"cwd": root, "scratchpad_dir": scratch})
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["decision"], "block")
            self.assertIn("just test", result["reason"])

    def test_blocks_with_no_suggestion_when_nothing_is_inferred(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as scratch,
        ):
            result = _invoke_main({"cwd": root, "scratchpad_dir": scratch})
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["decision"], "block")
            self.assertIn("Nothing could be inferred", result["reason"])

    def test_only_blocks_once_per_session(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as scratch,
        ):
            payload = {"cwd": root, "scratchpad_dir": scratch}
            first = _invoke_main(payload)
            second = _invoke_main(payload)
            self.assertIsNotNone(first)
            self.assertIsNone(second)

    def test_missing_scratchpad_dir_asks_every_time(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            payload = {"cwd": root}
            first = _invoke_main(payload)
            second = _invoke_main(payload)
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)


class VerificationRunTests(unittest.TestCase):
    def test_green_run_allows_and_resets_refusal_counter(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as scratch,
        ):
            config_path = Path(root) / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"verify": "true"}), encoding="utf-8")
            state_dir = Path(scratch) / "canon"
            state_dir.mkdir(parents=True)
            (state_dir / "consecutive_refusals").write_text("2", encoding="utf-8")

            result = _invoke_main({"cwd": root, "scratchpad_dir": scratch})

            self.assertIsNone(result)
            self.assertEqual(
                (state_dir / "consecutive_refusals").read_text(encoding="utf-8"), "0"
            )
            logged = _common.last_decision(Path(root), "stop.py")
            assert logged is not None
            self.assertEqual(logged["decision"], "allow")
            self.assertIn("passed", logged["reason"])

    def test_red_run_blocks_and_increments_refusal_counter(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as scratch,
        ):
            config_path = Path(root) / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"verify": "false"}), encoding="utf-8")

            result = _invoke_main({"cwd": root, "scratchpad_dir": scratch})

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["decision"], "block")
            self.assertIn("exited 1", result["reason"])
            counter = Path(scratch) / "canon" / "consecutive_refusals"
            self.assertEqual(counter.read_text(encoding="utf-8"), "1")
            logged = _common.last_decision(Path(root), "stop.py")
            assert logged is not None
            self.assertEqual(logged["decision"], "block")
            self.assertIn("exited 1", logged["reason"])

    def test_refusal_counter_cap_allows_through(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as scratch,
        ):
            config_path = Path(root) / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"verify": "false"}), encoding="utf-8")
            state_dir = Path(scratch) / "canon"
            state_dir.mkdir(parents=True)
            (state_dir / "consecutive_refusals").write_text(
                str(stop._MAX_CONSECUTIVE_REFUSALS), encoding="utf-8"
            )

            result = _invoke_main({"cwd": root, "scratchpad_dir": scratch})

            self.assertIsNone(result)
            self.assertEqual(
                (state_dir / "consecutive_refusals").read_text(encoding="utf-8"), "0"
            )
            logged = _common.last_decision(Path(root), "stop.py")
            assert logged is not None
            self.assertEqual(logged["decision"], "allow")
            self.assertIn("giving up after", logged["reason"])

    def test_verify_timeout_counts_as_red(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as scratch,
        ):
            config_path = Path(root) / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"verify": "sleep 5"}), encoding="utf-8")

            with mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="sleep 5", timeout=300),
            ):
                result = _invoke_main({"cwd": root, "scratchpad_dir": scratch})

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["decision"], "block")
            self.assertIn("timed out", result["reason"])


class RunVerificationUnitTests(unittest.TestCase):
    def test_passes_on_zero_exit(self) -> None:
        passed, detail = stop._run_verification(Path.cwd(), "true")
        self.assertTrue(passed)
        self.assertEqual(detail, "")

    def test_fails_on_nonzero_exit_with_output_attached(self) -> None:
        passed, detail = stop._run_verification(
            Path.cwd(), "python3 -c \"import sys; print('boom'); sys.exit(1)\""
        )
        self.assertFalse(passed)
        self.assertIn("boom", detail)

    def test_fails_on_unparsable_command(self) -> None:
        passed, detail = stop._run_verification(Path.cwd(), 'unterminated "quote')
        self.assertFalse(passed)
        self.assertIn("Could not parse", detail)

    def test_fails_on_missing_executable(self) -> None:
        passed, detail = stop._run_verification(
            Path.cwd(), "canon-nonexistent-command-xyz"
        )
        self.assertFalse(passed)
        self.assertIn("Could not run", detail)


if __name__ == "__main__":
    unittest.main()
