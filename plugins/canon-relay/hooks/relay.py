# SPDX-License-Identifier: BSD-3-Clause
"""canon-relay's one hook: carry a question the harness was about to ask
the developer to their Slack DM, and carry their answer back.

Three entry points, one per hooks.json entry:

- `relay.py permission` -- `PermissionRequest`. Allow or deny on the
  developer's behalf, but only with an answer they gave in Slack.
- `relay.py question` -- `PreToolUse` matched to `AskUserQuestion`. Answers
  it through `updatedInput`, which is the documented way a hook satisfies
  that tool: echo the original `questions` and add an `answers` map from
  question text to the chosen label.
- `relay.py idle` -- `Notification` matched to `idle_prompt`. A
  fire-and-forget DM that the session is waiting. Claude Code fires this
  about 60 seconds after a turn has actually ended, so it can never race
  Canon's own `Stop` gate.

**Every path fails open, and silence is the fail-open answer.** An unset
endpoint or token, a plain-HTTP endpoint that isn't loopback, an
unreachable server, a `204` (the developer isn't away), a `401` (the
device was revoked), a timeout, a malformed response: all of them print
nothing and exit 0. Claude Code then shows its normal local prompt, so the
worst case is exactly bare Claude Code.

**Whether to relay is the server's answer, not this hook's.** Presence
("away") is a fact about the developer, kept next to their Slack identity
on the relay server. This hook stores nothing and reads no state of its
own -- the endpoint and the device token come from the plugin's
`userConfig`, which Claude Code exports as `CLAUDE_PLUGIN_OPTION_<KEY>`
and keeps the sensitive one in the OS credential store.

**What leaves the machine is redacted here, before the request is built.**
A tool's name, a Bash command and its description (truncated), and file
paths -- never file contents, an Edit/Write body, tool output, or the
transcript. The Slack message only has to let a person decide; it never
has to reproduce the change.

Canon's own gates stay authoritative. `PreToolUse` runs before
`PermissionRequest`, so a command `git_guard.py` denies never reaches this
hook and can never be approved from Slack.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import _common

ENDPOINT_ENV = "CLAUDE_PLUGIN_OPTION_ENDPOINT"
TOKEN_ENV = "CLAUDE_PLUGIN_OPTION_DEVICE_TOKEN"

# The hook's own timeout in hooks.json is 600 s. The server expires a
# pending request well before that (see canon_relay/api.py), so the answer
# the developer sees in Slack -- "expired" -- is the one that actually
# happened, rather than the harness killing this process mid-read.
ASK_READ_TIMEOUT_SECONDS = 590.0
IDLE_TIMEOUT_SECONDS = 5.0

_COMMAND_LIMIT = 500
_FIELD_LIMIT = 200

# Tools whose permission dialog is the tool itself: the relay answers
# `AskUserQuestion` through its own `question` entry point, and approving a
# plan from a Slack button without reading it is not a thing to offer.
_NOT_RELAYED_AS_PERMISSION = ("AskUserQuestion", "ExitPlanMode")

# The one input field worth showing for each tool, where it has one. A
# tool not listed here is shown by name and its input's keys alone.
_SUMMARY_FIELDS = {
    "Read": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
    "Glob": "pattern",
    "Grep": "pattern",
    "WebFetch": "url",
    "WebSearch": "query",
}


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize(tool_name: str, tool_input: Any) -> dict[str, str]:
    """The redacted view of one tool call -- everything the relay sends."""
    summary: dict[str, str] = {"tool": _truncate(tool_name, _FIELD_LIMIT)}
    if not isinstance(tool_input, dict):
        return summary
    if tool_name == "Bash":
        command = tool_input.get("command")
        if isinstance(command, str):
            summary["command"] = _truncate(command, _COMMAND_LIMIT)
        description = tool_input.get("description")
        if isinstance(description, str) and description:
            summary["description"] = _truncate(description, _FIELD_LIMIT)
        return summary
    field = _SUMMARY_FIELDS.get(tool_name)
    if field is not None:
        value = tool_input.get(field)
        if isinstance(value, str):
            summary["target"] = _truncate(value, _FIELD_LIMIT)
        return summary
    keys = sorted(key for key in tool_input if isinstance(key, str))
    if keys:
        summary["keys"] = _truncate(", ".join(keys), _FIELD_LIMIT)
    return summary


def questions_view(tool_input: Any) -> list[dict[str, Any]] | None:
    """The questions an `AskUserQuestion` call carries, reduced to what a
    person needs to answer them. None if the input isn't recognisable."""
    if not isinstance(tool_input, dict):
        return None
    raw = tool_input.get("questions")
    if not isinstance(raw, list) or not raw:
        return None
    questions: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        text = item.get("question")
        options = item.get("options")
        if not isinstance(text, str) or not isinstance(options, list):
            return None
        labels: list[dict[str, str]] = []
        for option in options:
            if not isinstance(option, dict):
                return None
            label = option.get("label")
            if not isinstance(label, str):
                return None
            description = option.get("description")
            labels.append(
                {
                    "label": label,
                    "description": description if isinstance(description, str) else "",
                }
            )
        header = item.get("header")
        questions.append(
            {
                "question": text,
                "header": header if isinstance(header, str) else "",
                "options": labels,
                "multiSelect": item.get("multiSelect") is True,
            }
        )
    return questions


def endpoint_url(raw: str | None, path: str) -> str | None:
    """`raw` joined with `path`, or None if it isn't safe to send a token to.

    HTTPS always; plain HTTP only to a loopback host, which is what a
    local test server or an SSH tunnel looks like. Anything else would put
    the device token on the wire in the clear.
    """
    if not raw:
        return None
    parsed = urllib.parse.urlsplit(raw.strip())
    if parsed.scheme == "https" and parsed.hostname:
        pass
    elif parsed.scheme == "http" and parsed.hostname in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        pass
    else:
        return None
    return raw.strip().rstrip("/") + path


def _post(url: str, token: str, body: dict[str, Any], timeout: float) -> Any:
    """POST `body` and return the parsed JSON reply, or None.

    None covers every answer that means "not relayed": a `204`, any other
    non-200 status, a connection failure, a timeout, or a body that isn't
    a JSON object.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            parsed = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _context(payload: dict[str, Any]) -> dict[str, str]:
    root = _common.repo_root(payload)
    session = payload.get("session_id")
    return {
        "session": session if isinstance(session, str) else "",
        "machine": _truncate(socket.gethostname(), _FIELD_LIMIT),
        "repo": _truncate(Path(root).name, _FIELD_LIMIT),
        "branch": _truncate(_common.current_branch(root) or "", _FIELD_LIMIT),
    }


def _credentials() -> tuple[str, str] | None:
    token = os.environ.get(TOKEN_ENV, "").strip()
    endpoint = os.environ.get(ENDPOINT_ENV)
    if not token or not endpoint:
        return None
    return endpoint, token


def _emit(output: dict[str, Any]) -> None:
    json.dump(output, sys.stdout)


def handle_permission(payload: dict[str, Any]) -> None:
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str) or tool_name in _NOT_RELAYED_AS_PERMISSION:
        return
    credentials = _credentials()
    if credentials is None:
        return
    url = endpoint_url(credentials[0], "/v1/ask")
    if url is None:
        return
    body = {
        "kind": "permission",
        **_context(payload),
        **summarize(tool_name, payload.get("tool_input")),
    }
    reply = _post(url, credentials[1], body, ASK_READ_TIMEOUT_SECONDS)
    if reply is None:
        return
    outcome = reply.get("outcome")
    if outcome == "allow":
        decision: dict[str, Any] = {"behavior": "allow"}
    elif outcome == "deny":
        message = reply.get("message")
        decision = {
            "behavior": "deny",
            "message": message
            if isinstance(message, str) and message
            else "The developer denied this from Slack.",
        }
    else:
        return
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": decision,
            }
        }
    )


def handle_question(payload: dict[str, Any]) -> None:
    if payload.get("tool_name") != "AskUserQuestion":
        return
    tool_input = payload.get("tool_input")
    questions = questions_view(tool_input)
    if questions is None or not isinstance(tool_input, dict):
        return
    credentials = _credentials()
    if credentials is None:
        return
    url = endpoint_url(credentials[0], "/v1/ask")
    if url is None:
        return
    body = {"kind": "question", **_context(payload), "questions": questions}
    reply = _post(url, credentials[1], body, ASK_READ_TIMEOUT_SECONDS)
    if reply is None or reply.get("outcome") != "answers":
        return
    answers = reply.get("answers")
    known = {question["question"] for question in questions}
    if (
        not isinstance(answers, dict)
        or set(answers) != known
        or not all(isinstance(value, str) for value in answers.values())
    ):
        return
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {**tool_input, "answers": answers},
            }
        }
    )


def handle_idle(payload: dict[str, Any]) -> None:
    credentials = _credentials()
    if credentials is None:
        return
    url = endpoint_url(credentials[0], "/v1/idle")
    if url is None:
        return
    message = payload.get("message")
    body = {
        "kind": "idle",
        **_context(payload),
        "message": _truncate(message, _FIELD_LIMIT) if isinstance(message, str) else "",
    }
    _post(url, credentials[1], body, IDLE_TIMEOUT_SECONDS)


_HANDLERS = {
    "permission": handle_permission,
    "question": handle_question,
    "idle": handle_idle,
}


@_common.fail_open
def main() -> None:
    handler = _HANDLERS.get(sys.argv[1]) if len(sys.argv) > 1 else None
    payload = _common.read_payload()
    if handler is not None and payload is not None:
        handler(payload)
    sys.exit(0)


if __name__ == "__main__":
    main()
