# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_gh.py's ci_runs_for_commit and
evidence.py.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from canon_mcp import _gh, evidence


class CiRunsForCommitTests(unittest.TestCase):
    def test_parses_a_real_shaped_response(self) -> None:
        runs = [
            {
                "conclusion": "success",
                "createdAt": "2026-09-13T17:19:41Z",
                "databaseId": 34771252780,
                "status": "completed",
                "url": "https://github.com/urban233/Canon/actions/runs/1",
                "workflowName": "CI",
            }
        ]
        completed = mock.Mock(returncode=0, stdout=json.dumps(runs))
        with mock.patch("subprocess.run", return_value=completed):
            result = _gh.ci_runs_for_commit(Path("/repo"), "abc123")
        self.assertEqual(result, runs)

    def test_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=1, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_gh.ci_runs_for_commit(Path("/repo"), "abc123"))

    def test_returns_none_when_gh_is_unreachable(self) -> None:
        with mock.patch("subprocess.run", side_effect=OSError("no gh")):
            self.assertIsNone(_gh.ci_runs_for_commit(Path("/repo"), "abc123"))


class LatestRunTests(unittest.TestCase):
    def test_picks_the_run_with_the_latest_created_at_not_list_order(self) -> None:
        runs = [
            {"createdAt": "2026-01-01T00:00:00Z", "conclusion": "failure"},
            {"createdAt": "2026-06-01T00:00:00Z", "conclusion": "success"},
        ]
        latest = evidence._latest_run(runs)
        assert latest is not None
        self.assertEqual(latest["conclusion"], "success")

    def test_empty_list_yields_none(self) -> None:
        self.assertIsNone(evidence._latest_run([]))


class BuildEvidenceTests(unittest.TestCase):
    def test_pushed_and_green(self) -> None:
        runs = [
            {
                "createdAt": "2026-01-01T00:00:00Z",
                "status": "completed",
                "conclusion": "success",
            }
        ]
        with (
            mock.patch("canon_mcp.evidence.full_head_sha", return_value="abc123full"),
            mock.patch("canon_mcp.evidence.is_pushed", return_value=True),
            mock.patch("canon_mcp.evidence.ci_runs_for_commit", return_value=runs),
        ):
            result = evidence.build_evidence(Path("/repo"))
        self.assertTrue(result["pushed"])
        self.assertEqual(result["source"], "ci")
        self.assertTrue(result["green"])

    def test_pushed_but_ci_failed(self) -> None:
        runs = [
            {
                "createdAt": "2026-01-01T00:00:00Z",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
        with (
            mock.patch("canon_mcp.evidence.full_head_sha", return_value="abc123full"),
            mock.patch("canon_mcp.evidence.is_pushed", return_value=True),
            mock.patch("canon_mcp.evidence.ci_runs_for_commit", return_value=runs),
        ):
            result = evidence.build_evidence(Path("/repo"))
        self.assertFalse(result["green"])

    def test_pushed_but_no_run_found_yet(self) -> None:
        with (
            mock.patch("canon_mcp.evidence.full_head_sha", return_value="abc123full"),
            mock.patch("canon_mcp.evidence.is_pushed", return_value=True),
            mock.patch("canon_mcp.evidence.ci_runs_for_commit", return_value=[]),
        ):
            result = evidence.build_evidence(Path("/repo"))
        self.assertTrue(result["pushed"])
        self.assertIsNone(result["green"])
        self.assertEqual(result["runs"], [])

    def test_not_pushed_and_no_verify_signal(self) -> None:
        with (
            mock.patch("canon_mcp.evidence.full_head_sha", return_value="abc123full"),
            mock.patch("canon_mcp.evidence.is_pushed", return_value=False),
            mock.patch("canon_mcp.evidence.load_config", return_value=None),
        ):
            result = evidence.build_evidence(Path("/repo"))
        self.assertFalse(result["pushed"])
        self.assertIsNone(result["source"])
        self.assertIn("no verify command", result["message"])

    def test_not_pushed_runs_a_real_local_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch(
                    "canon_mcp.evidence.full_head_sha", return_value="abc123full"
                ),
                mock.patch("canon_mcp.evidence.is_pushed", return_value=False),
                mock.patch(
                    "canon_mcp.evidence.load_config", return_value={"verify": "true"}
                ),
            ):
                result = evidence.build_evidence(Path(tmp))
        self.assertEqual(result["source"], "local_rerun")
        self.assertEqual(result["command"], "true")
        self.assertTrue(result["green"])

    def test_not_pushed_reports_a_failing_local_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch(
                    "canon_mcp.evidence.full_head_sha", return_value="abc123full"
                ),
                mock.patch("canon_mcp.evidence.is_pushed", return_value=False),
                mock.patch(
                    "canon_mcp.evidence.load_config", return_value={"verify": "false"}
                ),
            ):
                result = evidence.build_evidence(Path(tmp))
        self.assertFalse(result["green"])
        self.assertIn("exited", result["detail"])

    def test_compound_verify_command_is_reported_as_unknown_not_red(self) -> None:
        """A `.canon/config.json` fault -- here, a command Canon runs
        with no shell would silently mishandle -- must land as `green:
        None` with an explanatory message, the same shape as "not
        configured yet," never as `green: False`, which `ship.py`'s
        `_evidence_reason` would read as "the configured verification
        failed."."""
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch(
                    "canon_mcp.evidence.full_head_sha", return_value="abc123full"
                ),
                mock.patch("canon_mcp.evidence.is_pushed", return_value=False),
                mock.patch(
                    "canon_mcp.evidence.load_config",
                    return_value={"verify": "ruff check . && pytest"},
                ),
            ):
                result = evidence.build_evidence(Path(tmp))
        self.assertIsNone(result["green"])
        self.assertIn(".canon/config.json", result["message"])
        self.assertIn("&&", result["message"])

    def test_missing_binary_is_reported_as_unknown_not_red(self) -> None:
        """Discovered only at execution time, unlike the compound case
        above -- but it must land in the exact same place."""
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch(
                    "canon_mcp.evidence.full_head_sha", return_value="abc123full"
                ),
                mock.patch("canon_mcp.evidence.is_pushed", return_value=False),
                mock.patch(
                    "canon_mcp.evidence.load_config",
                    return_value={"verify": "canon-nonexistent-command-xyz"},
                ),
            ):
                result = evidence.build_evidence(Path(tmp))
        self.assertIsNone(result["green"])
        self.assertIn(".canon/config.json", result["message"])

    def test_a_compound_plan_header_override_names_the_plan_file(self) -> None:
        """The configuration fault must name the file that actually
        resolved to this command. Here that's the plan header, not
        `.canon/config.json` -- which names a perfectly runnable "true"
        -- so sending a human to edit `.canon/config.json` would point
        them at the wrong file. Mirrors
        tests/test_claude_hooks_stop.py's
        `test_a_compound_plan_header_override_is_also_caught`."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / ".canon" / "plans"
            plan.mkdir(parents=True)
            (plan / "wip.md").write_text(
                '---\nstatus: approved\nverify: "ruff check . && pytest"\n---\n\n'
                "## Approach\nx\n",
                encoding="utf-8",
            )
            with (
                mock.patch(
                    "canon_mcp.evidence.full_head_sha", return_value="abc123full"
                ),
                mock.patch("canon_mcp.evidence.is_pushed", return_value=False),
                mock.patch("canon_mcp.evidence.current_branch", return_value="wip"),
                mock.patch(
                    "canon_mcp.evidence.load_config",
                    return_value={"verify": "true"},
                ),
            ):
                result = evidence.build_evidence(root)
        self.assertIsNone(result["green"])
        self.assertIn(".canon/plans/wip.md", result["message"])
        self.assertNotIn(".canon/config.json", result["message"])


if __name__ == "__main__":
    unittest.main()
