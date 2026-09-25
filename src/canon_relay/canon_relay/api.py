# SPDX-License-Identifier: BSD-3-Clause
"""What the relay does, independent of HTTP and of Slack.

`web.py` turns an HTTP request into a call here and `app.py` turns a Slack
action into one; neither holds any logic of its own worth testing. This
module is standard library only, so it runs under Bazel.

The rules, in the order `ask` applies them:

1. **An unknown or revoked token gets 401**, and the hook stays silent.
2. **A present developer gets 204 immediately.** The hook stays silent and
   the local prompt appears after one round trip. Nothing is posted to
   Slack: the relay only speaks up when the developer said they were away.
3. **Otherwise the request is posted to the owner's DM and held** until
   they answer, say `back`, press *Answer at terminal*, or it expires. Only
   an answer produces a 200; every other ending is a 204, which the hook
   treats exactly like "not relayed".
4. **If Slack can't be reached, the request fails open** -- 204, local
   prompt -- rather than waiting on a message nobody can see.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from . import pending as pending_mod
from .pending import Outcome, Pending, Registry
from .store import Developer, Store

# Below the hook's own 590 s read timeout and hooks.json's 600 s, so the
# relay -- not the harness -- decides when a request has expired, and the
# Slack message says so.
DEFAULT_EXPIRY_SECONDS = 540.0

_FIELD_LIMIT = 200
_COMMAND_LIMIT = 500
_MAX_QUESTIONS = 4
_MAX_OPTIONS = 12

_CONTEXT_FIELDS = ("session", "machine", "repo", "branch")
_PERMISSION_FIELDS = {
    "tool": _FIELD_LIMIT,
    "command": _COMMAND_LIMIT,
    "description": _FIELD_LIMIT,
    "target": _FIELD_LIMIT,
    "keys": _FIELD_LIMIT,
}


class Notifier(Protocol):
    """The Slack side, as `Relay` needs it. `app.SlackNotifier` is the real
    one; tests pass a fake."""

    async def post_request(self, developer: Developer, request: Pending) -> None: ...

    async def close_request(self, request: Pending, outcome: Outcome) -> None: ...

    async def post_idle(
        self, developer: Developer, payload: dict[str, Any]
    ) -> None: ...


@dataclass
class Reply:
    status: int
    body: dict[str, Any] | None = None


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _context(body: dict[str, Any]) -> dict[str, str]:
    return {name: _text(body.get(name), _FIELD_LIMIT) for name in _CONTEXT_FIELDS}


def clean_permission(body: dict[str, Any]) -> dict[str, Any] | None:
    tool = body.get("tool")
    if not isinstance(tool, str) or not tool:
        return None
    cleaned: dict[str, Any] = _context(body)
    for name, limit in _PERMISSION_FIELDS.items():
        value = _text(body.get(name), limit)
        if value:
            cleaned[name] = value
    return cleaned


def clean_questions(body: dict[str, Any]) -> dict[str, Any] | None:
    raw = body.get("questions")
    if not isinstance(raw, list) or not 0 < len(raw) <= _MAX_QUESTIONS:
        return None
    questions: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        text = item.get("question")
        options = item.get("options")
        if not isinstance(text, str) or not text or not isinstance(options, list):
            return None
        if not 0 < len(options) <= _MAX_OPTIONS:
            return None
        cleaned_options: list[dict[str, str]] = []
        for option in options:
            if not isinstance(option, dict):
                return None
            label = option.get("label")
            if not isinstance(label, str) or not label:
                return None
            cleaned_options.append(
                {
                    "label": label,
                    "description": _text(option.get("description"), _FIELD_LIMIT),
                }
            )
        questions.append(
            {
                "question": text,
                "header": _text(item.get("header"), _FIELD_LIMIT),
                "options": cleaned_options,
                "multiSelect": item.get("multiSelect") is True,
            }
        )
    if len({question["question"] for question in questions}) != len(questions):
        return None
    return {**_context(body), "questions": questions}


def answers_from_selection(
    questions: list[dict[str, Any]],
    choices: dict[int, list[int]],
    typed: dict[int, str],
) -> dict[str, str] | None:
    """The `answers` map `AskUserQuestion` expects, or None if incomplete.

    `choices` maps a question's index to the indexes of the options picked
    for it; `typed` maps a question's index to free text, which wins. The
    labels come from the request the server is holding, never from the
    Slack payload, so a crafted action can only choose among the options
    Claude actually offered. Multi-select answers join labels with commas,
    as the tool's own reference describes.
    """
    answers: dict[str, str] = {}
    for index, question in enumerate(questions):
        text = typed.get(index, "").strip()
        if text:
            answers[question["question"]] = text
            continue
        options = question["options"]
        picked = choices.get(index, [])
        if not picked or any(not 0 <= choice < len(options) for choice in picked):
            return None
        if not question["multiSelect"] and len(picked) != 1:
            return None
        labels = [options[choice]["label"] for choice in sorted(set(picked))]
        answers[question["question"]] = ", ".join(labels)
    return answers


class Relay:
    def __init__(
        self,
        store: Store,
        registry: Registry,
        notifier: Notifier,
        expiry_seconds: float = DEFAULT_EXPIRY_SECONDS,
    ) -> None:
        self.store = store
        self.registry = registry
        self.notifier = notifier
        self.expiry_seconds = expiry_seconds

    def _authenticate(self, authorization: str | None) -> Developer | None:
        token = _bearer(authorization)
        if token is None:
            return None
        found = self.store.authenticate(token)
        return found[1] if found is not None else None

    async def ask(self, authorization: str | None, body: Any) -> Reply:
        developer = self._authenticate(authorization)
        if developer is None:
            return Reply(401)
        if not isinstance(body, dict):
            return Reply(400)
        raw_kind = body.get("kind")
        kind = raw_kind if isinstance(raw_kind, str) else ""
        if kind == "permission":
            payload = clean_permission(body)
        elif kind == "question":
            payload = clean_questions(body)
        else:
            payload = None
        if payload is None:
            return Reply(400)
        if not developer.away:
            return Reply(204)

        request = self.registry.create(developer.id, kind, payload)
        try:
            try:
                await self.notifier.post_request(developer, request)
            except Exception:  # noqa: BLE001 - Slack down means local prompt
                return Reply(204)
            outcome = await self._wait(request)
            await self._close(request, outcome)
            if outcome.kind in (pending_mod.ALLOW, pending_mod.DENY):
                return (
                    Reply(200, outcome.reply()) if kind == "permission" else Reply(204)
                )
            if outcome.kind == pending_mod.ANSWERS and kind == "question":
                return Reply(200, outcome.reply())
            return Reply(204)
        except asyncio.CancelledError:
            # The hook went away -- answered at the terminal, killed, or the
            # session ended. Say so in Slack so nobody answers into a void.
            await self._close(request, Outcome(pending_mod.RELEASE, actor="gone"))
            raise
        finally:
            self.registry.discard(request.id)

    async def _wait(self, request: Pending) -> Outcome:
        try:
            return await asyncio.wait_for(
                asyncio.shield(request.future), self.expiry_seconds
            )
        except TimeoutError:
            return Outcome(pending_mod.RELEASE, actor="expired")

    async def _close(self, request: Pending, outcome: Outcome) -> None:
        try:
            await self.notifier.close_request(request, outcome)
        except Exception:  # noqa: BLE001 - a stale Slack message is cosmetic
            pass

    async def idle(self, authorization: str | None, body: Any) -> Reply:
        developer = self._authenticate(authorization)
        if developer is None:
            return Reply(401)
        if not isinstance(body, dict):
            return Reply(400)
        if not developer.away:
            return Reply(204)
        payload = {
            **_context(body),
            "message": _text(body.get("message"), _FIELD_LIMIT),
        }
        try:
            await self.notifier.post_idle(developer, payload)
        except Exception:  # noqa: BLE001 - an idle notice is best-effort
            return Reply(204)
        return Reply(202)

    def answer(
        self, slack_team: str, slack_user: str, request_id: str, outcome: Outcome
    ) -> str:
        """Resolve a request from a Slack action. See `Registry.resolve`."""
        developer = self.store.developer(slack_team, slack_user)
        return self.registry.resolve(request_id, developer.id, outcome)

    def request_for(
        self, slack_team: str, slack_user: str, request_id: str
    ) -> Pending | None:
        """The pending request, only if this Slack user owns it."""
        request = self.registry.get(request_id)
        if request is None or request.future.done():
            return None
        developer = self.store.developer(slack_team, slack_user)
        return request if request.developer_id == developer.id else None

    def set_presence(self, slack_team: str, slack_user: str, away: bool) -> int:
        """Record presence; on `back`, release every pending request to the
        terminal. Returns how many were released."""
        developer = self.store.developer(slack_team, slack_user)
        self.store.set_away(developer.id, away)
        if away:
            return 0
        return len(self.registry.release_all(developer.id, actor="back"))
