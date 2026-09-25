# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/canon-relay/hooks/relay.py.

A stdlib `http.server` stands in for canon-relay-server, so each test
states the exact reply and checks the exact hook output -- or that the
hook stayed silent, which is what failing open means here.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from unittest import mock

import relay

_TOKEN = "crd_test-token"


class _FakeRelay:
    """Records what the hook sent, answers with a preset status and body."""

    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body
        self.requests: list[dict[str, Any]] = []


@contextmanager
def _serve(fake: _FakeRelay) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server's naming
            length = int(self.headers.get("Content-Length", "0"))
            fake.requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(length)),
                }
            )
            self.send_response(fake.status)
            if fake.body is None:
                self.end_headers()
                return
            data = json.dumps(fake.body).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    # http.server logs every request to stderr; swallowed here rather than
    # by overriding `log_message`, which strict pyrefly would want an
    # `@override` for -- and `typing.override` is newer than the 3.9 floor.
    with redirect_stderr(io.StringIO()):
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()


def _run(entry: str, payload: dict[str, Any], env: dict[str, str]) -> str:
    buffer = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=False):
        with mock.patch.object(sys, "argv", ["relay.py", entry]):
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                with mock.patch("sys.stdout", buffer):
                    with mock.patch("sys.exit"):
                        relay.main()
    return buffer.getvalue()


def _env(endpoint: str) -> dict[str, str]:
    return {relay.ENDPOINT_ENV: endpoint, relay.TOKEN_ENV: _TOKEN}


_BASH = {
    "session_id": "s1",
    "cwd": "/tmp",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {"command": "git push origin fix/parser", "description": "Push"},
}

_EDIT = {
    "session_id": "s1",
    "cwd": "/tmp",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Edit",
    "tool_input": {
        "file_path": "/tmp/secret.py",
        "old_string": "API_KEY = 'old'",
        "new_string": "API_KEY = 'hunter2'",
    },
}

_QUESTION_INPUT = {
    "questions": [
        {
            "question": "Which database?",
            "header": "DB",
            "options": [
                {"label": "SQLite", "description": "Small"},
                {"label": "Postgres", "description": "Big"},
            ],
            "multiSelect": False,
        }
    ]
}

_QUESTION = {
    "session_id": "s1",
    "cwd": "/tmp",
    "hook_event_name": "PreToolUse",
    "tool_name": "AskUserQuestion",
    "tool_input": _QUESTION_INPUT,
}


class PermissionTests(unittest.TestCase):
    def test_allow_from_slack_allows(self) -> None:
        fake = _FakeRelay(200, {"outcome": "allow"})
        with _serve(fake) as url:
            output = _run("permission", _BASH, _env(url))
        self.assertEqual(
            json.loads(output),
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "allow"},
                }
            },
        )
        self.assertEqual(fake.requests[0]["path"], "/v1/ask")
        self.assertEqual(fake.requests[0]["authorization"], f"Bearer {_TOKEN}")

    def test_deny_carries_the_developers_reason(self) -> None:
        fake = _FakeRelay(200, {"outcome": "deny", "message": "not on a Friday"})
        with _serve(fake) as url:
            output = _run("permission", _BASH, _env(url))
        decision = json.loads(output)["hookSpecificOutput"]["decision"]
        self.assertEqual(decision, {"behavior": "deny", "message": "not on a Friday"})

    def test_deny_without_reason_still_explains(self) -> None:
        fake = _FakeRelay(200, {"outcome": "deny"})
        with _serve(fake) as url:
            output = _run("permission", _BASH, _env(url))
        decision = json.loads(output)["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["behavior"], "deny")
        self.assertIn("Slack", decision["message"])

    def test_present_developer_is_silent(self) -> None:
        fake = _FakeRelay(204)
        with _serve(fake) as url:
            self.assertEqual(_run("permission", _BASH, _env(url)), "")
        self.assertEqual(len(fake.requests), 1)

    def test_revoked_device_is_silent(self) -> None:
        with _serve(_FakeRelay(401)) as url:
            self.assertEqual(_run("permission", _BASH, _env(url)), "")

    def test_release_is_silent(self) -> None:
        with _serve(_FakeRelay(200, {"outcome": "release"})) as url:
            self.assertEqual(_run("permission", _BASH, _env(url)), "")

    def test_unreachable_server_is_silent(self) -> None:
        with _serve(_FakeRelay(204)) as url:
            dead = url
        self.assertEqual(_run("permission", _BASH, _env(dead)), "")

    def test_unconfigured_plugin_sends_nothing(self) -> None:
        fake = _FakeRelay(200, {"outcome": "allow"})
        with _serve(fake) as url:
            env = {relay.ENDPOINT_ENV: url, relay.TOKEN_ENV: ""}
            self.assertEqual(_run("permission", _BASH, env), "")
        self.assertEqual(fake.requests, [])

    def test_ask_user_question_is_not_relayed_as_a_permission(self) -> None:
        fake = _FakeRelay(200, {"outcome": "allow"})
        payload = {**_QUESTION, "hook_event_name": "PermissionRequest"}
        with _serve(fake) as url:
            self.assertEqual(_run("permission", payload, _env(url)), "")
        self.assertEqual(fake.requests, [])

    def test_bash_command_and_description_are_sent(self) -> None:
        fake = _FakeRelay(204)
        with _serve(fake) as url:
            _run("permission", _BASH, _env(url))
        body = fake.requests[0]["body"]
        self.assertEqual(body["kind"], "permission")
        self.assertEqual(body["tool"], "Bash")
        self.assertEqual(body["command"], "git push origin fix/parser")
        self.assertEqual(body["description"], "Push")
        self.assertEqual(body["session"], "s1")

    def test_edit_body_never_leaves_the_machine(self) -> None:
        fake = _FakeRelay(204)
        with _serve(fake) as url:
            _run("permission", _EDIT, _env(url))
        sent = json.dumps(fake.requests[0]["body"])
        self.assertNotIn("hunter2", sent)
        self.assertNotIn("old_string", sent)
        self.assertEqual(fake.requests[0]["body"]["target"], "/tmp/secret.py")

    def test_long_command_is_truncated(self) -> None:
        fake = _FakeRelay(204)
        payload = {**_BASH, "tool_input": {"command": "x" * 5000}}
        with _serve(fake) as url:
            _run("permission", payload, _env(url))
        self.assertEqual(len(fake.requests[0]["body"]["command"]), 500)

    def test_unknown_tool_sends_only_its_input_keys(self) -> None:
        fake = _FakeRelay(204)
        payload = {
            **_BASH,
            "tool_name": "mcp__db__query",
            "tool_input": {"sql": "SELECT secret FROM users"},
        }
        with _serve(fake) as url:
            _run("permission", payload, _env(url))
        body = fake.requests[0]["body"]
        self.assertEqual(body["keys"], "sql")
        self.assertNotIn("SELECT", json.dumps(body))


class QuestionTests(unittest.TestCase):
    def test_answers_come_back_through_updated_input(self) -> None:
        fake = _FakeRelay(
            200, {"outcome": "answers", "answers": {"Which database?": "SQLite"}}
        )
        with _serve(fake) as url:
            output = _run("question", _QUESTION, _env(url))
        self.assertEqual(
            json.loads(output),
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": {
                        **_QUESTION_INPUT,
                        "answers": {"Which database?": "SQLite"},
                    },
                }
            },
        )
        self.assertEqual(fake.requests[0]["body"]["kind"], "question")
        self.assertEqual(
            fake.requests[0]["body"]["questions"][0]["options"][1]["label"],
            "Postgres",
        )

    def test_answers_for_the_wrong_questions_are_ignored(self) -> None:
        fake = _FakeRelay(200, {"outcome": "answers", "answers": {"Other?": "x"}})
        with _serve(fake) as url:
            self.assertEqual(_run("question", _QUESTION, _env(url)), "")

    def test_malformed_questions_send_nothing(self) -> None:
        fake = _FakeRelay(204)
        payload = {**_QUESTION, "tool_input": {"questions": "not a list"}}
        with _serve(fake) as url:
            self.assertEqual(_run("question", payload, _env(url)), "")
        self.assertEqual(fake.requests, [])

    def test_present_developer_is_silent(self) -> None:
        with _serve(_FakeRelay(204)) as url:
            self.assertEqual(_run("question", _QUESTION, _env(url)), "")


class IdleTests(unittest.TestCase):
    def test_idle_posts_the_notification_text_and_prints_nothing(self) -> None:
        fake = _FakeRelay(202)
        payload = {
            "session_id": "s1",
            "cwd": "/tmp",
            "hook_event_name": "Notification",
            "notification_type": "idle_prompt",
            "message": "Claude is waiting for your input",
        }
        with _serve(fake) as url:
            self.assertEqual(_run("idle", payload, _env(url)), "")
        self.assertEqual(fake.requests[0]["path"], "/v1/idle")
        self.assertEqual(
            fake.requests[0]["body"]["message"], "Claude is waiting for your input"
        )


class EntryPointTests(unittest.TestCase):
    def test_unknown_entry_point_is_silent(self) -> None:
        fake = _FakeRelay(200, {"outcome": "allow"})
        with _serve(fake) as url:
            self.assertEqual(_run("nonsense", _BASH, _env(url)), "")
        self.assertEqual(fake.requests, [])

    def test_malformed_stdin_is_silent(self) -> None:
        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", ["relay.py", "permission"]):
            with mock.patch.object(sys, "stdin", io.StringIO("{not json")):
                with mock.patch("sys.stdout", buffer):
                    with mock.patch("sys.exit"):
                        relay.main()
        self.assertEqual(buffer.getvalue(), "")


class EndpointTests(unittest.TestCase):
    def test_https_is_accepted(self) -> None:
        self.assertEqual(
            relay.endpoint_url("https://relay.example.org/", "/v1/ask"),
            "https://relay.example.org/v1/ask",
        )

    def test_plain_http_is_refused_off_loopback(self) -> None:
        self.assertIsNone(relay.endpoint_url("http://relay.example.org", "/v1/ask"))

    def test_plain_http_to_loopback_is_accepted(self) -> None:
        self.assertEqual(
            relay.endpoint_url("http://localhost:8787", "/v1/ask"),
            "http://localhost:8787/v1/ask",
        )

    def test_nonsense_is_refused(self) -> None:
        self.assertIsNone(relay.endpoint_url("relay.example.org", "/v1/ask"))
        self.assertIsNone(relay.endpoint_url("", "/v1/ask"))


if __name__ == "__main__":
    unittest.main()
