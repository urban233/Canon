# SPDX-License-Identifier: BSD-3-Clause
"""Tests for the Antigravity hook dialect in `_common.py`.

Antigravity is the third platform Canon ships for, and the only one
whose hook payloads and results are shaped differently from Claude
Code's. Rather than fork the nine shared hook modules to gain three
payload keys, `_common.py` normalizes an Antigravity payload on the way
in and picks the matching result dialect on the way out -- so every
other hook file stays byte-identical across all three plugins.

This file tests that seam, because it is the only place the three
platforms actually differ, and because two of its properties fail
silently rather than loudly if they regress:

- The `Stop` decision is spelled *inversely* on the two dialects.
  Claude Code and Codex read `"block"` as "do not stop"; Antigravity
  reads `"continue"` as "do not stop" and treats every other value,
  the word `"block"` included, as permission to stop. Emitting the
  wrong word does not error -- it lets a red turn end, which is the
  single failure the Stop gate exists to prevent.
- The edit-tool matcher list decides whether the plan gate, scope check
  and fast check ever fire at all. A missing tool name produces a gate
  that is simply never invoked, and nothing announces that.

Every payload shape asserted here was captured from a live `agy`
session, not read off a schema -- see docs/antigravity-hook-surface.md.
"""

from __future__ import annotations

import io
import json
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stdout, suppress
from typing import Any
from unittest import mock

import _common
import git_guard

# One real `PreToolUse` payload, as captured from `agy --print`. The
# envelope keys are camelCase; the tool call's own arguments are
# PascalCase, which is the detail a schema summary would lose.
_REAL_PRE_TOOL_USE: dict[str, Any] = {
    "artifactDirectoryPath": "/Users/x/.gemini/antigravity-cli/brain/abc-123",
    "conversationId": "abc-123",
    "modelName": "gemini-3.8-flash-high",
    "stepIdx": 4,
    "toolCall": {
        "args": {
            "CommandLine": "pwd",
            "Cwd": "/repo",
            "WaitMsBeforeAsync": 2000,
            "toolAction": "Checking current directory",
            "toolSummary": "Get working directory",
        },
        "name": "run_command",
    },
    "transcriptPath": "/Users/x/.gemini/antigravity-cli/brain/abc-123/t.jsonl",
    "workspacePaths": [],
}


def _read(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Run `read_payload` against `payload` on stdin."""
    with mock.patch.object(_common.sys, "stdin", io.StringIO(json.dumps(payload))):
        return _common.read_payload()


def _emitted(call: Callable[[], None]) -> dict[str, Any] | None:
    """Run an emitting helper and return the JSON it wrote, if any.

    Every emitter ends on `SystemExit`, which is the point -- a hook says
    one thing and stops -- so that is suppressed rather than treated as a
    failure.
    """
    buffer = io.StringIO()
    with redirect_stdout(buffer), suppress(SystemExit):
        call()
    raw = buffer.getvalue()
    return json.loads(raw) if raw else None


@contextmanager
def _host(name: str) -> Iterator[None]:
    """Pin the dialect for one block, and restore it afterwards.

    `_common` keeps the detected host in module state, because the
    emitters take no payload argument -- threading one through them
    would mean editing every hook file, which is the duplication this
    whole seam exists to avoid. That makes it global, so a test that
    sets it must put it back.
    """
    previous = _common._host
    _common._host = name
    try:
        yield
    finally:
        _common._host = previous


class HostDetectionTest(unittest.TestCase):
    def test_an_antigravity_payload_switches_the_dialect(self) -> None:
        _read(_REAL_PRE_TOOL_USE)
        self.assertEqual(_common.host(), _common.HOST_ANTIGRAVITY)

    def test_a_claude_code_payload_leaves_the_default_dialect(self) -> None:
        _read({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/repo"})
        self.assertEqual(_common.host(), _common.HOST_DEFAULT)

    def test_an_unparseable_payload_does_not_switch_the_dialect(self) -> None:
        with mock.patch.object(_common.sys, "stdin", io.StringIO("not json")):
            self.assertIsNone(_common.read_payload())
        self.assertEqual(_common.host(), _common.HOST_DEFAULT)


class NormalizationTest(unittest.TestCase):
    def test_the_tool_call_becomes_tool_name_and_tool_input(self) -> None:
        payload = _read(_REAL_PRE_TOOL_USE)
        assert payload is not None
        self.assertEqual(payload["tool_name"], "run_command")
        self.assertEqual(payload["tool_input"]["command"], "pwd")

    def test_an_edit_target_is_reachable_as_a_file_path(self) -> None:
        payload = _read(
            {
                "conversationId": "c",
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": "/repo/src/a.py",
                        "CodeContent": "x = 1\n",
                        "Overwrite": True,
                    },
                },
            }
        )
        self.assertEqual(_common.edited_paths(payload), ["/repo/src/a.py"])

    def test_a_workspace_path_becomes_the_repo_root(self) -> None:
        payload = dict(_REAL_PRE_TOOL_USE, workspacePaths=["/repo"])
        self.assertEqual(str(_common.repo_root(_read(payload))), "/repo")

    def test_an_absolute_tool_cwd_stands_in_for_an_empty_workspace(self) -> None:
        # `workspacePaths` is empty in `agy --print` sessions, and the
        # hook's own process cwd is the plugin directory, not the repo.
        self.assertEqual(str(_common.repo_root(_read(_REAL_PRE_TOOL_USE))), "/repo")

    def test_a_relative_tool_cwd_is_not_trusted_as_the_repo_root(self) -> None:
        payload = json.loads(json.dumps(_REAL_PRE_TOOL_USE))
        payload["toolCall"]["args"]["Cwd"] = "."
        normalized = _read(payload)
        assert normalized is not None
        self.assertNotIn("cwd", normalized)

    def test_the_conversation_id_becomes_the_session_id(self) -> None:
        payload = _read(_REAL_PRE_TOOL_USE)
        assert payload is not None
        self.assertEqual(payload["session_id"], "abc-123")

    def test_the_artifact_directory_becomes_the_state_directory(self) -> None:
        payload = _read(_REAL_PRE_TOOL_USE)
        state = _common.state_dir(payload)
        assert state is not None
        # Used as given: it is already per-conversation, so the id is
        # not appended a second time.
        self.assertEqual(
            str(state), "/Users/x/.gemini/antigravity-cli/brain/abc-123/canon"
        )

    def test_a_later_execution_reads_as_an_active_stop_hook(self) -> None:
        first = _read({"conversationId": "c", "executionNum": 1})
        later = _read({"conversationId": "c", "executionNum": 2})
        assert first is not None and later is not None
        self.assertFalse(first["stop_hook_active"])
        self.assertTrue(later["stop_hook_active"])

    def test_the_original_camelcase_keys_survive_normalization(self) -> None:
        payload = _read(_REAL_PRE_TOOL_USE)
        assert payload is not None
        self.assertEqual(payload["stepIdx"], 4)
        self.assertEqual(
            payload["transcriptPath"], _REAL_PRE_TOOL_USE["transcriptPath"]
        )


class ResultDialectTest(unittest.TestCase):
    def test_allow_states_a_decision_without_granting_permission(self) -> None:
        # A live session confirmed a hook's `allow` leaves the user's own
        # permission prompt where it was; only `permissionOverrides`
        # grants anything, and Canon never emits one.
        with _host(_common.HOST_ANTIGRAVITY):
            result = _emitted(_common.allow)
        self.assertEqual(result, {"decision": "allow"})
        self.assertNotIn("permissionOverrides", result or {})

    def test_deny_carries_its_reason(self) -> None:
        with _host(_common.HOST_ANTIGRAVITY):
            result = _emitted(lambda: _common.deny("no force pushes"))
        self.assertEqual(result, {"decision": "deny", "reason": "no force pushes"})

    def test_ask_carries_its_reason(self) -> None:
        with _host(_common.HOST_ANTIGRAVITY):
            result = _emitted(lambda: _common.ask("confirm?"))
        self.assertEqual(result, {"decision": "ask", "reason": "confirm?"})

    def test_refusing_a_stop_says_continue_not_block(self) -> None:
        with _host(_common.HOST_ANTIGRAVITY):
            result = _emitted(lambda: _common.block("tests are red"))
        assert result is not None
        # The inversion: "block" here would read as permission to stop.
        self.assertEqual(result["decision"], "continue")
        self.assertEqual(result["reason"], "tests are red")

    def test_context_is_injected_as_an_ephemeral_step(self) -> None:
        with _host(_common.HOST_ANTIGRAVITY):
            result = _emitted(lambda: _common.context("SessionStart", "on branch x"))
        self.assertEqual(result, {"injectSteps": [{"ephemeralMessage": "on branch x"}]})


class DefaultDialectIsUnchangedTest(unittest.TestCase):
    """The Antigravity seam must not alter what the other two receive."""

    def test_allow_stays_silent(self) -> None:
        with _host(_common.HOST_DEFAULT):
            self.assertIsNone(_emitted(_common.allow))

    def test_refusing_a_stop_still_says_block(self) -> None:
        with _host(_common.HOST_DEFAULT):
            result = _emitted(lambda: _common.block("tests are red"))
        assert result is not None
        self.assertEqual(result["decision"], "block")

    def test_deny_keeps_its_envelope(self) -> None:
        with _host(_common.HOST_DEFAULT):
            result = _emitted(lambda: _common.deny("nope"))
        assert result is not None
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")


class EditToolNamesTest(unittest.TestCase):
    def test_every_antigravity_file_writing_tool_is_covered(self) -> None:
        # Read off the model-facing tool list the language server itself
        # ships. A name missing here is a gate that never fires.
        for name in (
            "write_to_file",
            "replace_file_content",
            "multi_replace_file_content",
            "edit_file",
        ):
            self.assertIn(name, _common.EDIT_TOOL_NAMES)

    def test_the_other_platforms_tools_are_still_covered(self) -> None:
        for name in ("Edit", "Write", "apply_patch"):
            self.assertIn(name, _common.EDIT_TOOL_NAMES)


class GitGuardOnAntigravityTest(unittest.TestCase):
    def test_the_shell_tool_is_recognized_by_its_antigravity_name(self) -> None:
        self.assertIn("run_command", git_guard._SHELL_TOOL_NAMES)

    def test_a_force_push_is_denied_in_the_antigravity_dialect(self) -> None:
        payload = json.loads(json.dumps(_REAL_PRE_TOOL_USE))
        payload["toolCall"]["args"]["CommandLine"] = "git push --force origin main"
        payload["workspacePaths"] = ["/repo"]
        buffer = io.StringIO()
        with (
            mock.patch.object(_common.sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(git_guard._config, "canon_is_active", return_value=True),
            mock.patch.object(git_guard._common, "log_decision"),
            redirect_stdout(buffer),
            suppress(SystemExit),
        ):
            git_guard.main()
        result = json.loads(buffer.getvalue())
        self.assertEqual(result["decision"], "deny")
        self.assertIn("force push", result["reason"])

    def test_a_rewritten_command_comes_back_under_overwrite(self) -> None:
        buffer = io.StringIO()
        with (
            _host(_common.HOST_ANTIGRAVITY),
            redirect_stdout(buffer),
            suppress(SystemExit),
        ):
            git_guard._allow_with_updated_command(
                {"command": "old"}, "git commit -m 'x'"
            )
        result = json.loads(buffer.getvalue())
        # Keyed by the tool's own argument name, not the snake_case view.
        self.assertEqual(result["overwrite"], {"CommandLine": "git commit -m 'x'"})
        self.assertEqual(result["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
