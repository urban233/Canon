# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/fast_check.py.

Covers the two ways this hook stays quiet that matter most -- a pass, and
a timeout -- alongside the debounce window, the once-per-session
configuration-fault report, and the inert paths. The timeout case has its
own test because silence there is a deliberate design decision rather
than an omission: see the hook's module docstring on why an advisory
layer must not report a build-tool lock wait as a failure.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import _common
import fast_check


def _configure(root: Path, **keys: str) -> None:
    """Write `.canon/config.json`. `verify` is always set unless a test
    overrides it, because Canon is inert without one and an inert hook
    would pass every behavioural test here for the wrong reason."""
    config: dict[str, str] = {"verify": "true"}
    config.update(keys)
    path = root / ".canon" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")


def _payload(root: Path, state: Path | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "cwd": str(root),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(root / "src" / "foo.py")},
    }
    if state is not None:
        payload["scratchpad_dir"] = str(state)
    payload.update(extra)
    return payload


def _invoke_main(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            with mock.patch("sys.stdout", buffer):
                fast_check.main()
    return buffer.getvalue()


class InertPathTests(unittest.TestCase):
    def test_silent_without_a_verification_signal(self) -> None:
        """docs/plan.md §07: no `verify` means Canon does not act at all,
        not that it acts a little. A `check` alone does not switch it
        on."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".canon" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"check": "true"}), encoding="utf-8")
            self.assertEqual(_invoke_main(_payload(root)), "")

    def test_silent_when_the_repository_declares_no_check(self) -> None:
        """Layer one is opt-in: absent `check` is simply the behaviour
        Canon had before this hook existed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _configure(root)
            self.assertEqual(_invoke_main(_payload(root)), "")

    def test_silent_for_a_tool_that_is_not_an_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _configure(root, check="false")
            self.assertEqual(
                _invoke_main(_payload(root, tool_name="Bash")),
                "",
            )

    def test_silent_when_no_touched_path_can_be_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _configure(root, check="false")
            self.assertEqual(_invoke_main(_payload(root, tool_input={})), "")


class OutcomeTests(unittest.TestCase):
    def test_a_passing_check_says_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _configure(root, check="true")
            self.assertEqual(_invoke_main(_payload(root)), "")

    def test_a_failing_check_is_reported_as_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _configure(
                root, check="python3 -c \"import sys; print('boom'); sys.exit(1)\""
            )
            output = _invoke_main(_payload(root))
            self.assertIn("additionalContext", output)
            self.assertIn("boom", output)
            self.assertIn("blocks nothing", output)

    def test_a_failing_check_never_blocks(self) -> None:
        """`PostToolUse` could not deny even if it wanted to -- the edit
        has already happened -- and §11 gives layer one no authority. The
        emitted payload must carry no permission decision at all."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _configure(root, check="false")
            emitted = json.loads(_invoke_main(_payload(root)))
            self.assertNotIn("decision", emitted)
            self.assertNotIn("permissionDecision", json.dumps(emitted))

    def test_a_timeout_says_nothing_at_all(self) -> None:
        """The design point this hook exists to get right.

        A `check` and a `verify` are usually the same build tool, and a
        build tool serialises per output base -- so a timeout here is far
        more likely to be this hook waiting on a lock another Canon gate
        holds than a real regression. Reported as a failure it would be
        indistinguishable from one, and an advisory layer that cries wolf
        is one a developer learns to ignore. Layer one has no authority,
        so an unknown answer costs nothing.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _configure(root, check="sleep 300")
            timed_out = _common.CommandResult(
                passed=False,
                detail="`sleep 300` timed out after 60s.",
                configuration_fault=False,
                timed_out=True,
            )
            with mock.patch.object(_common, "run_command", return_value=timed_out):
                self.assertEqual(_invoke_main(_payload(root)), "")


class ConfigurationFaultTests(unittest.TestCase):
    def test_a_compound_check_is_reported_as_configuration_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            _configure(root, check="ruff check . && pytest")
            output = _invoke_main(_payload(root, state=state))
            self.assertIn("cannot be run as configured", output)
            self.assertIn(".canon/config.json", output)
            self.assertIn("not something", output)

    def test_the_configuration_fault_is_reported_once_per_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            _configure(root, check="ruff check . && pytest")
            first = _invoke_main(_payload(root, state=state))
            second = _invoke_main(_payload(root, state=state))
            self.assertIn("cannot be run as configured", first)
            self.assertEqual(second, "")

    def test_a_missing_binary_is_a_configuration_fault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            _configure(root, check="canon-nonexistent-command-xyz")
            output = _invoke_main(_payload(root, state=state))
            self.assertIn("cannot be run as configured", output)


class DebounceTests(unittest.TestCase):
    def test_a_second_edit_inside_the_window_does_not_rerun_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            _configure(root, check="false")
            first = _invoke_main(_payload(root, state=state))
            second = _invoke_main(_payload(root, state=state))
            self.assertIn("additionalContext", first)
            self.assertEqual(second, "")

    def test_the_check_runs_again_once_the_window_has_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            _configure(root, check="false")
            self.assertIn(
                "additionalContext", _invoke_main(_payload(root, state=state))
            )
            with mock.patch.object(fast_check, "_DEBOUNCE_SECONDS", 0):
                self.assertIn(
                    "additionalContext", _invoke_main(_payload(root, state=state))
                )

    def test_without_session_state_the_check_runs_every_time(self) -> None:
        """No `scratchpad_dir` and no `session_id` means no state to
        debounce with. Degrading to "run every time" keeps the hook
        working where it cannot remember, which is the opposite trade
        from `stop.py`'s counter -- there an always-empty counter would
        block forever, here it merely costs a repeat."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _configure(root, check="false")
            self.assertIn("additionalContext", _invoke_main(_payload(root)))
            self.assertIn("additionalContext", _invoke_main(_payload(root)))


if __name__ == "__main__":
    unittest.main()
