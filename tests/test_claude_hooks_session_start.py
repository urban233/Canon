# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/session_start.py.

Covers each derived fact's happy path and its independent degradation
(no plan file, no config, no git, no `gh`, malformed `gh` output) -- the
properties Step 5's plan calls out as non-negotiable for this hook.
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

import session_start


def _invoke_main(payload: dict[str, object]) -> str:
    """Run `session_start.main()` and return the injected `additionalContext`."""
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.stdout", buffer):
            with mock.patch("sys.exit"):
                session_start.main()
    result = json.loads(buffer.getvalue())
    return result["hookSpecificOutput"]["additionalContext"]


class CheckSummaryTests(unittest.TestCase):
    def test_none_rollup_is_none(self) -> None:
        self.assertIsNone(session_start._check_summary(None))

    def test_empty_rollup_is_none(self) -> None:
        self.assertIsNone(session_start._check_summary([]))

    def test_counts_each_classification(self) -> None:
        rollup = [
            {"conclusion": "SUCCESS"},
            {"conclusion": "SUCCESS"},
            {"conclusion": "FAILURE"},
            {"state": "PENDING"},
        ]
        self.assertEqual(
            session_start._check_summary(rollup), "2 passing, 1 failing, 1 pending"
        )


class PlanStatusTests(unittest.TestCase):
    def test_no_plan_file_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            status = session_start._plan_status(Path(root), "feature/widget")
            self.assertIn("none saved for this branch yet", status)

    def test_reads_status_from_header(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan_path = Path(root) / ".canon" / "plans" / "feature" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(
                "---\nstatus: approved\nbase:\n---\n\nbody", encoding="utf-8"
            )
            status = session_start._plan_status(Path(root), "feature/widget")
            self.assertTrue(status.startswith("approved"))

    def test_unknown_status_when_header_has_no_status_field(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan_path = Path(root) / ".canon" / "plans" / "solo.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text("---\nbase:\n---\n\nbody", encoding="utf-8")
            status = session_start._plan_status(Path(root), "solo")
            self.assertTrue(status.startswith("unknown"))


class VerifyStatusTests(unittest.TestCase):
    def test_not_configured_yet(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                session_start._verify_status(Path(root)), "not configured yet"
            )

    def test_reads_configured_verify_command(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            config_path = Path(root) / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps({"verify": "just test"}), encoding="utf-8"
            )
            self.assertEqual(session_start._verify_status(Path(root)), "`just test`")


class DiffSummaryTests(unittest.TestCase):
    def test_none_base_yields_none(self) -> None:
        self.assertIsNone(session_start._diff_summary(Path("/repo"), None))

    def test_reports_shortstat_output(self) -> None:
        completed = mock.Mock(
            returncode=0, stdout=" 3 files changed, 42 insertions(+)\n"
        )
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(
                session_start._diff_summary(Path("/repo"), "abc123"),
                "3 files changed, 42 insertions(+)",
            )

    def test_no_changes_is_reported_explicitly(self) -> None:
        completed = mock.Mock(returncode=0, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(
                session_start._diff_summary(Path("/repo"), "abc123"), "no changes yet"
            )

    def test_git_failure_yields_none(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(session_start._diff_summary(Path("/repo"), "abc123"))


class PrStatusTests(unittest.TestCase):
    def test_gh_unavailable(self) -> None:
        with mock.patch("subprocess.run", side_effect=OSError("no gh")):
            self.assertEqual(
                session_start._pr_status(Path("/repo")), "unknown (gh unavailable)"
            )

    def test_no_open_pr(self) -> None:
        completed = mock.Mock(returncode=1, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(
                session_start._pr_status(Path("/repo")), "none open for this branch"
            )

    def test_open_pr_with_checks(self) -> None:
        stdout = json.dumps(
            {
                "number": 12,
                "state": "OPEN",
                "statusCheckRollup": [
                    {"conclusion": "SUCCESS"},
                    {"conclusion": "SUCCESS"},
                    {"state": "PENDING"},
                ],
            }
        )
        completed = mock.Mock(returncode=0, stdout=stdout)
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(
                session_start._pr_status(Path("/repo")),
                "#12 (open): 2 passing, 1 pending",
            )

    def test_malformed_json_degrades_gracefully(self) -> None:
        completed = mock.Mock(returncode=0, stdout="not json")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(
                session_start._pr_status(Path("/repo")),
                "unknown (unexpected gh output)",
            )

    def test_timeout_degrades_gracefully(self) -> None:
        with mock.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=15),
        ):
            self.assertEqual(
                session_start._pr_status(Path("/repo")), "unknown (gh unavailable)"
            )


class MainTests(unittest.TestCase):
    def test_position_line_assembles_all_pieces(self) -> None:
        with tempfile.TemporaryDirectory() as root_str:
            root = Path(root_str)
            config_path = root / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps({"verify": "just test"}), encoding="utf-8"
            )
            plan_path = root / ".canon" / "plans" / "feature" / "widget.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text("---\nstatus: approved\n---\n\nbody", encoding="utf-8")

            with mock.patch("_common.current_branch", return_value="feature/widget"):
                with mock.patch("_common.default_branch", return_value="main"):
                    with mock.patch("_common.merge_base", return_value=None):
                        with mock.patch("subprocess.run", side_effect=OSError("no gh")):
                            context = _invoke_main({"cwd": str(root)})

            self.assertIn("branch `feature/widget`", context)
            self.assertIn("Plan: approved", context)
            self.assertIn("Verify: `just test`", context)
            self.assertIn("PR: unknown (gh unavailable)", context)
            self.assertNotIn("Diff vs", context)


if __name__ == "__main__":
    unittest.main()
