# SPDX-License-Identifier: BSD-3-Clause
"""Slack Block Kit views, as plain dicts. No Slack SDK here.

Every interactive element carries only an opaque request ID (and, for a
question, an option's index). What the button *means* -- the command, the
labels -- is looked up in the request the server is holding, never read
back from the Slack payload.
"""

from __future__ import annotations

from typing import Any

from .pending import ALLOW, ANSWERS, DENY, Outcome, Pending

ALLOW_ACTION = "canon_relay_allow"
DENY_ACTION = "canon_relay_deny"
DENY_REASON_ACTION = "canon_relay_deny_reason"
TERMINAL_ACTION = "canon_relay_terminal"
SUBMIT_ACTION = "canon_relay_submit"
TYPE_ACTION = "canon_relay_type"
PICK_ACTION_PREFIX = "canon_relay_pick_"
PRESENCE_ACTION = "canon_relay_presence"

DENY_REASON_VIEW = "canon_relay_deny_reason_view"
TYPED_ANSWER_VIEW = "canon_relay_typed_answer_view"

REASON_BLOCK = "reason"
REASON_INPUT = "reason_input"
TYPED_BLOCK_PREFIX = "typed_"
TYPED_INPUT = "typed_input"

_OPTION_TEXT_LIMIT = 75
_DENY_REASON_LIMIT = 2000


def escape(text: str) -> str:
    """Slack mrkdwn escaping: the three characters Slack itself reserves."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _code(text: str) -> str:
    # A literal ``` inside the command would end the block early.
    return "```" + escape(text).replace("```", "`​``") + "```"


def _plain(text: str, limit: int = 150) -> dict[str, Any]:
    clipped = text if len(text) <= limit else text[: limit - 1] + "…"
    return {"type": "plain_text", "text": clipped or " ", "emoji": True}


def _button(
    label: str, action_id: str, value: str, style: str | None = None
) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": _plain(label),
        "action_id": action_id,
        "value": value,
    }
    if style is not None:
        button["style"] = style
    return button


def _where(payload: dict[str, Any]) -> dict[str, Any]:
    parts = [
        f"*{escape(payload[name])}*" if name == "repo" else escape(payload[name])
        for name in ("repo", "branch", "machine")
        if payload.get(name)
    ]
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": " · ".join(parts) or "Claude Code"}],
    }


def permission_summary(payload: dict[str, Any]) -> str:
    lines = [f"*{escape(payload['tool'])}*"]
    if payload.get("command"):
        lines.append(_code(payload["command"]))
    if payload.get("target"):
        lines.append(f"`{escape(payload['target'])}`")
    if payload.get("keys"):
        lines.append(f"input: {escape(payload['keys'])}")
    if payload.get("description"):
        lines.append(f"_{escape(payload['description'])}_")
    return "\n".join(lines)


def permission_message(request: Pending) -> list[dict[str, Any]]:
    payload = request.payload
    return [
        {"type": "header", "text": _plain("Claude Code needs your permission")},
        _where(payload),
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": permission_summary(payload)},
        },
        {
            "type": "actions",
            "block_id": "canon_relay_permission",
            "elements": [
                _button("Allow", ALLOW_ACTION, request.id, "primary"),
                _button("Deny", DENY_ACTION, request.id, "danger"),
                _button("Deny with reason…", DENY_REASON_ACTION, request.id),
                _button("Answer at terminal", TERMINAL_ACTION, request.id),
            ],
        },
    ]


def _question_blocks(index: int, question: dict[str, Any]) -> list[dict[str, Any]]:
    title = question["question"]
    if question.get("header"):
        title = f"{question['header']}: {title}"
    described = [
        f"*{escape(option['label'])}* — {escape(option['description'])}"
        for option in question["options"]
        if option.get("description")
    ]
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{escape(title)}*"}}
    ]
    if described:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "\n".join(described)}],
            }
        )
    options = [
        {"text": _plain(option["label"], _OPTION_TEXT_LIMIT), "value": str(number)}
        for number, option in enumerate(question["options"])
    ]
    select: dict[str, Any] = {
        "type": "multi_static_select" if question["multiSelect"] else "static_select",
        "action_id": f"{PICK_ACTION_PREFIX}{index}",
        "placeholder": _plain(
            "Choose…" if not question["multiSelect"] else "Choose any"
        ),
        "options": options,
    }
    blocks.append({"type": "actions", "block_id": f"q{index}", "elements": [select]})
    return blocks


def question_message(request: Pending) -> list[dict[str, Any]]:
    payload = request.payload
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": _plain("Claude Code has a question")},
        _where(payload),
    ]
    for index, question in enumerate(payload["questions"]):
        blocks.extend(_question_blocks(index, question))
    blocks.append(
        {
            "type": "actions",
            "block_id": "canon_relay_question",
            "elements": [
                _button("Submit", SUBMIT_ACTION, request.id, "primary"),
                _button("Type an answer…", TYPE_ACTION, request.id),
                _button("Answer at terminal", TERMINAL_ACTION, request.id),
            ],
        }
    )
    return blocks


def request_message(request: Pending) -> list[dict[str, Any]]:
    if request.kind == "question":
        return question_message(request)
    return permission_message(request)


def request_fallback(request: Pending) -> str:
    """The notification text Slack shows where blocks can't render."""
    repo = request.payload.get("repo") or "Claude Code"
    if request.kind == "question":
        return f"{repo}: Claude Code has a question"
    return f"{repo}: Claude Code wants to use {request.payload.get('tool', 'a tool')}"


def outcome_line(outcome: Outcome) -> str:
    if outcome.kind == ALLOW:
        return ":white_check_mark: Allowed from Slack."
    if outcome.kind == DENY:
        if outcome.message:
            return f":no_entry: Denied from Slack: _{escape(outcome.message)}_"
        return ":no_entry: Denied from Slack."
    if outcome.kind == ANSWERS:
        answered = "\n".join(
            f"• {escape(question)} → *{escape(answer)}*"
            for question, answer in outcome.answers.items()
        )
        return f":speech_balloon: Answered from Slack.\n{answered}"
    if outcome.actor == "expired":
        return ":hourglass: Expired. The question is waiting at your terminal."
    if outcome.actor == "gone":
        return ":leftwards_arrow_with_hook: The session stopped waiting for this."
    return ":leftwards_arrow_with_hook: Sent back to your terminal."


def closed_message(request: Pending, outcome: Outcome) -> list[dict[str, Any]]:
    """The message after the request ended: what was asked, and how it
    ended, with every button gone."""
    payload = request.payload
    if request.kind == "question":
        asked = "\n".join(
            f"*{escape(question['question'])}*" for question in payload["questions"]
        )
        title = "Claude Code had a question"
    else:
        asked = permission_summary(payload)
        title = "Claude Code asked for permission"
    return [
        {"type": "header", "text": _plain(title)},
        _where(payload),
        {"type": "section", "text": {"type": "mrkdwn", "text": asked}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": outcome_line(outcome)}],
        },
    ]


def idle_message(payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": _plain("Claude Code is waiting for you")},
        _where(payload),
    ]
    if payload.get("message"):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": escape(payload["message"])},
            }
        )
    return blocks


def deny_reason_modal(request_id: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": DENY_REASON_VIEW,
        "private_metadata": request_id,
        "title": _plain("Deny with reason"),
        "submit": _plain("Deny"),
        "close": _plain("Cancel"),
        "blocks": [
            {
                "type": "input",
                "block_id": REASON_BLOCK,
                "label": _plain("Why? Claude reads this."),
                "element": {
                    "type": "plain_text_input",
                    "action_id": REASON_INPUT,
                    "multiline": True,
                    "max_length": _DENY_REASON_LIMIT,
                },
            }
        ],
    }


def typed_answer_modal(request: Pending) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for index, question in enumerate(request.payload["questions"]):
        blocks.append(
            {
                "type": "input",
                "block_id": f"{TYPED_BLOCK_PREFIX}{index}",
                "optional": True,
                "label": _plain(question["question"]),
                "element": {
                    "type": "plain_text_input",
                    "action_id": TYPED_INPUT,
                    "max_length": _DENY_REASON_LIMIT,
                },
            }
        )
    return {
        "type": "modal",
        "callback_id": TYPED_ANSWER_VIEW,
        "private_metadata": request.id,
        "title": _plain("Answer Claude"),
        "submit": _plain("Send"),
        "close": _plain("Cancel"),
        "blocks": blocks,
    }


def home_view(away: bool, device_names: list[str]) -> dict[str, Any]:
    if away:
        status = (
            "You're *away*. A local session that needs you will ask here, "
            "and its terminal prompt waits until you answer."
        )
        toggle = _button("I'm back", PRESENCE_ACTION, "back", "primary")
    else:
        status = (
            "You're *present*. The relay stays quiet and every prompt "
            "appears at your terminal as usual."
        )
        toggle = _button("I'm away", PRESENCE_ACTION, "away")
    devices = (
        "\n".join(f"• {escape(name)}" for name in device_names)
        if device_names
        else "No linked devices. Send me `link <name>` to link one."
    )
    return {
        "type": "home",
        "blocks": [
            {"type": "header", "text": _plain("Canon relay")},
            {"type": "section", "text": {"type": "mrkdwn", "text": status}},
            {"type": "actions", "elements": [toggle]},
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Devices*\n{devices}"},
            },
        ],
    }
