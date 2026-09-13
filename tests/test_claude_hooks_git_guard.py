# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/git_guard.py."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import git_guard


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    _activate(root)


def _activate(root: Path) -> None:
    """Give `root` a verification signal.

    Canon is inert without one (docs/plan.md §07, "No signal, no
    Canon"), so a fixture with no `verify` command exercises the inert
    path rather than the behaviour under test. Every test here that is
    not specifically about going inert calls this.
    """
    config_path = root / ".canon" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"verify": "true"}), encoding="utf-8")


def _invoke_main(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            with mock.patch("sys.stdout", buffer):
                git_guard.main()
    return buffer.getvalue()


def _payload(root: Path, command: str) -> dict[str, Any]:
    return {
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


class DestructiveCommandTests(unittest.TestCase):
    def _assert_denied(self, command: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            self.assertEqual(
                payload["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_force_push_long_flag(self) -> None:
        self._assert_denied("git push --force origin main")

    def test_force_push_short_flag(self) -> None:
        self._assert_denied("git push -f origin main")

    def test_hard_reset(self) -> None:
        self._assert_denied("git reset --hard HEAD~1")

    def test_forced_clean(self) -> None:
        self._assert_denied("git clean -fd")

    def test_forced_clean_flag_order_reversed(self) -> None:
        self._assert_denied("git clean -df")

    def test_local_branch_delete(self) -> None:
        self._assert_denied("git branch -D feature/x")

    def test_remote_branch_delete_via_push(self) -> None:
        self._assert_denied("git push origin --delete feature/x")

    def test_merge(self) -> None:
        self._assert_denied("git merge feature/x")

    def test_merge_with_flags(self) -> None:
        self._assert_denied("git merge --no-ff feature/x")

    def test_remote_branch_delete_via_empty_refspec(self) -> None:
        self._assert_denied("git push origin :feature/x")

    def test_safe_push_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, "git push origin feature/x"))
            self.assertEqual(output, "")

    def test_unrelated_command_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, "git status"))
            self.assertEqual(output, "")

    def test_still_denied_outright_in_pair_mode(self) -> None:
        """Destructive commands are never a question with an answer a
        mode could change -- see git_guard.py's own module docstring."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            config_path = root / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps({"verify": "true", "mode": "pair"}), encoding="utf-8"
            )
            output = _invoke_main(_payload(root, "git push --force origin main"))
            payload = json.loads(output)
            self.assertEqual(
                payload["hookSpecificOutput"]["permissionDecision"], "deny"
            )


class NearMissTests(unittest.TestCase):
    """Commands that a looser pattern would deny, and must not.

    Every entry here was denied before this test class existed. A
    `deny` from this hook has no `ask` and no override, so a false
    positive is a command the developer simply cannot run -- worth a
    named regression test each rather than one blanket assertion.
    """

    def _assert_allowed(self, command: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            self.assertEqual(_invoke_main(_payload(root, command)), "")

    def test_merge_base_is_read_only(self) -> None:
        """canon-mcp's own `_git.merge_base` shells out to exactly this."""
        self._assert_allowed("git merge-base HEAD main")

    def test_merge_file_is_not_a_branch_merge(self) -> None:
        self._assert_allowed("git merge-file a.txt base.txt b.txt")

    def test_merge_abort_is_recovery_not_a_merge(self) -> None:
        self._assert_allowed("git merge --abort")

    def test_merge_quit_is_recovery(self) -> None:
        self._assert_allowed("git merge --quit")

    def test_colon_refspec_push_is_an_ordinary_push(self) -> None:
        """Only an *empty* source side deletes; this one creates."""
        self._assert_allowed("git push origin HEAD:refs/heads/feature/x")

    def test_log_merges_is_read_only(self) -> None:
        self._assert_allowed("git log --merges")


class InertWithoutVerificationSignalTests(unittest.TestCase):
    """docs/plan.md §07: "Not the gate alone -- the whole plugin."

    See docs/decisions/0001-what-inert-means.md for the two hooks this
    deliberately does not apply to.
    """

    def test_a_destructive_command_is_not_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / ".canon" / "config.json").unlink()
            self.assertEqual(
                _invoke_main(_payload(root, "git push --force origin main")), ""
            )

    def test_an_attribution_trailer_is_not_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / ".canon" / "config.json").unlink()
            command = 'git commit -m "x\n\nCo-Authored-By: A Model <a@b.c>"'
            self.assertEqual(_invoke_main(_payload(root, command)), "")


class AttributionStrippingTests(unittest.TestCase):
    def test_strips_a_co_authored_by_trailer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                "git commit -m \"$(cat <<'EOF'\n"
                "feat: thing\n\n"
                "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
                'EOF\n)"'
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", hook_output["updatedInput"]["command"])
            self.assertIn("feat: thing", hook_output["updatedInput"]["command"])

    def test_commit_without_a_trailer_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, 'git commit -m "fix: thing"'))
            self.assertEqual(output, "")


class MiscTests(unittest.TestCase):
    def test_noop_for_unrelated_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(
                {"cwd": str(root), "tool_name": "Read", "tool_input": {}}
            )
            self.assertEqual(output, "")

    def test_noop_when_command_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(
                {"cwd": str(root), "tool_name": "Bash", "tool_input": {}}
            )
            self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
