# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_hooks/capture_review.py's one generalization made
for the Codex port: matching `agent_type` by substring and logging under
a normalized key, rather than requiring exact equality.

tests/test_claude_hooks_capture_review.py already exercises the bare,
unnamespaced form (`"reviewer"`, `"risk-reviewer"`) via the byte-identical
vendored copy at plugins/claude/hooks/capture_review.py, including the
exact scenarios this generalization was written to keep passing -- these
tests cover only what that suite cannot: a namespaced `agent_type`, which
Claude Code's own `SubagentStop` matcher pattern documents
(`<plugin>:reviewer`) but which this port could not confirm the exact
form of for Codex (see docs/codex-hook-surface.md).
"""

from __future__ import annotations

import unittest

import capture_review

_READY = "READY FOR HUMAN APPROVAL"


class MatchKnownAgentTests(unittest.TestCase):
    def test_bare_reviewer_matches(self) -> None:
        self.assertEqual(capture_review._match_known_agent("reviewer"), "reviewer")

    def test_bare_risk_reviewer_matches(self) -> None:
        self.assertEqual(
            capture_review._match_known_agent("risk-reviewer"), "risk-reviewer"
        )

    def test_namespaced_reviewer_matches_and_normalizes(self) -> None:
        self.assertEqual(
            capture_review._match_known_agent("canon:reviewer"), "reviewer"
        )

    def test_namespaced_risk_reviewer_matches_and_normalizes(self) -> None:
        self.assertEqual(
            capture_review._match_known_agent("canon:risk-reviewer"), "risk-reviewer"
        )

    def test_risk_reviewer_is_not_misread_as_plain_reviewer(self) -> None:
        """ "risk-reviewer" contains "reviewer" as a substring -- the more
        specific name must win, on either platform's naming scheme."""
        self.assertEqual(
            capture_review._match_known_agent("some-risk-reviewer-thread"),
            "risk-reviewer",
        )

    def test_none_defaults_to_reviewer(self) -> None:
        self.assertEqual(capture_review._match_known_agent(None), "reviewer")

    def test_an_unrelated_agent_type_does_not_match(self) -> None:
        self.assertIsNone(capture_review._match_known_agent("Explore"))


def _invoke_main(payload: dict[str, object]) -> None:
    import io
    import json
    import sys
    from unittest import mock

    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            capture_review.main()


class NamespacedAgentEndToEndTests(unittest.TestCase):
    def test_a_namespaced_risk_reviewer_verdict_logs_under_the_normalized_key(
        self,
    ) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"verify": "true"}))
            completed = mock.Mock(returncode=0, stdout="abc1234def\n")
            with mock.patch("subprocess.run", return_value=completed):
                _invoke_main(
                    {
                        "cwd": str(root),
                        "agent_type": "codex:risk-reviewer",
                        "last_assistant_message": (
                            f"Migration is reversible.\n\n{_READY}"
                        ),
                    }
                )
            log_path = root / ".canon" / "hooks" / "decisions.jsonl"
            self.assertTrue(log_path.exists())
            record = json.loads(log_path.read_text().strip())
            self.assertEqual(record["hook"], "risk-reviewer")
            self.assertEqual(record["decision"], _READY)


if __name__ == "__main__":
    unittest.main()
