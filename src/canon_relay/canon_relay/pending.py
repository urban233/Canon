# SPDX-License-Identifier: BSD-3-Clause
"""Requests waiting for a developer's answer -- held in memory, never stored.

A pending request exists exactly as long as the hook connection waiting on
it. It ends one of four ways: the owner answers in Slack, the owner says
`back` (or presses *Answer at terminal*), it expires, or the hook goes
away. Each resolves or discards the future, and nothing is left behind to
reconcile. A server restart drops every one, and each waiting hook falls
back to the local prompt -- the relay's version of "every gate fails open".

Request IDs are random and opaque. A Slack button carries only the ID,
never the command or the question text, and resolving one checks that the
Slack user acting is the developer who owns it.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any

# How a request ended, as the hook sees it. "release" means "not answered
# here, go to the terminal", which the hook turns into silence.
ALLOW = "allow"
DENY = "deny"
ANSWERS = "answers"
RELEASE = "release"


@dataclass
class Outcome:
    kind: str
    message: str = ""
    answers: dict[str, str] = field(default_factory=dict)
    actor: str = ""

    def reply(self) -> dict[str, Any]:
        """The JSON body the waiting hook receives."""
        body: dict[str, Any] = {"outcome": self.kind}
        if self.kind == DENY and self.message:
            body["message"] = self.message
        if self.kind == ANSWERS:
            body["answers"] = dict(self.answers)
        return body


@dataclass
class Pending:
    id: str
    developer_id: int
    kind: str
    payload: dict[str, Any]
    future: asyncio.Future[Outcome]
    # Where the Slack message for this request was posted, so it can be
    # updated in place once the request ends. Set by the notifier.
    channel: str = ""
    ts: str = ""


class Registry:
    def __init__(self) -> None:
        self._pending: dict[str, Pending] = {}

    def create(self, developer_id: int, kind: str, payload: dict[str, Any]) -> Pending:
        request_id = "rq_" + secrets.token_urlsafe(12)
        future: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()
        pending = Pending(request_id, developer_id, kind, payload, future)
        self._pending[request_id] = pending
        return pending

    def get(self, request_id: str) -> Pending | None:
        return self._pending.get(request_id)

    def resolve(self, request_id: str, developer_id: int, outcome: Outcome) -> str:
        """Resolve one request on its owner's behalf.

        Returns "ok", "gone" (no such request, or it already ended), or
        "not_owner" -- the one check that keeps Alice from answering Bob's
        session.
        """
        pending = self._pending.get(request_id)
        if pending is None or pending.future.done():
            return "gone"
        if pending.developer_id != developer_id:
            return "not_owner"
        pending.future.set_result(outcome)
        return "ok"

    def release_all(self, developer_id: int, actor: str = "") -> list[Pending]:
        """Send every one of this developer's pending requests back to the
        terminal -- what `back` means."""
        released: list[Pending] = []
        for pending in list(self._pending.values()):
            if pending.developer_id == developer_id and not pending.future.done():
                pending.future.set_result(Outcome(RELEASE, actor=actor))
                released.append(pending)
        return released

    def discard(self, request_id: str) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is not None and not pending.future.done():
            pending.future.cancel()

    def __len__(self) -> int:
        return len(self._pending)
