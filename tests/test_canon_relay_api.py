# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_relay/canon_relay/api.py and pending.py.

A fake notifier stands in for Slack, so each test drives the relay the way
a hook and a Slack click would, and checks what the hook gets back.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

from canon_relay.api import Relay, answers_from_selection, clean_questions
from canon_relay.pending import Outcome, Pending, Registry
from canon_relay.store import Developer, Store

from canon_relay import pending


class _FakeNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.posted: list[Pending] = []
        self.closed: list[tuple[Pending, Outcome]] = []
        self.idle: list[dict[str, Any]] = []
        self.posted_event = asyncio.Event()

    async def post_request(self, developer: Developer, request: Pending) -> None:
        if self.fail:
            raise RuntimeError("slack is down")
        self.posted.append(request)
        self.posted_event.set()

    async def close_request(self, request: Pending, outcome: Outcome) -> None:
        self.closed.append((request, outcome))

    async def post_idle(self, developer: Developer, payload: dict[str, Any]) -> None:
        self.idle.append(payload)


_PERMISSION = {
    "kind": "permission",
    "session": "s1",
    "machine": "laptop",
    "repo": "canon",
    "branch": "feat/x",
    "tool": "Bash",
    "command": "git push",
}

_QUESTIONS = [
    {
        "question": "Which database?",
        "header": "DB",
        "options": [{"label": "SQLite"}, {"label": "Postgres"}],
        "multiSelect": False,
    },
    {
        "question": "Which extras?",
        "header": "",
        "options": [{"label": "cache"}, {"label": "search"}, {"label": "auth"}],
        "multiSelect": True,
    },
]


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def _set_up(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "relay.sqlite3")
        self.addCleanup(self.store.close)
        self.notifier = _FakeNotifier()
        self.relay = Relay(self.store, Registry(), self.notifier, expiry_seconds=5)
        alice = self.store.developer("T1", "UA")
        token = self.store.link(alice.id, "laptop")
        assert token is not None
        self.auth = f"Bearer {token}"

    def _away(self, user: str = "UA") -> None:
        self.relay.set_presence("T1", user, True)

    async def _ask_until_posted(self, body: dict[str, Any]) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(self.relay.ask(self.auth, body))
        await asyncio.wait_for(self.notifier.posted_event.wait(), 2)
        return task

    async def test_bad_token_is_401(self) -> None:
        await self._set_up()
        reply = await self.relay.ask("Bearer crd_wrong", _PERMISSION)
        self.assertEqual(reply.status, 401)
        self.assertEqual((await self.relay.ask(None, _PERMISSION)).status, 401)

    async def test_present_developer_gets_204_and_nothing_is_posted(self) -> None:
        await self._set_up()
        reply = await self.relay.ask(self.auth, _PERMISSION)
        self.assertEqual(reply.status, 204)
        self.assertEqual(self.notifier.posted, [])

    async def test_malformed_body_is_400(self) -> None:
        await self._set_up()
        self._away()
        self.assertEqual((await self.relay.ask(self.auth, {"kind": "x"})).status, 400)
        self.assertEqual((await self.relay.ask(self.auth, [])).status, 400)
        no_tool = {**_PERMISSION, "tool": ""}
        self.assertEqual((await self.relay.ask(self.auth, no_tool)).status, 400)

    async def test_allow_from_the_owner_reaches_the_hook(self) -> None:
        await self._set_up()
        self._away()
        task = await self._ask_until_posted(_PERMISSION)
        request = self.notifier.posted[0]
        self.assertEqual(request.payload["command"], "git push")
        result = self.relay.answer("T1", "UA", request.id, Outcome(pending.ALLOW))
        self.assertEqual(result, "ok")
        reply = await task
        self.assertEqual((reply.status, reply.body), (200, {"outcome": "allow"}))
        self.assertEqual(self.notifier.closed[0][1].kind, pending.ALLOW)
        self.assertEqual(len(self.relay.registry), 0)

    async def test_deny_carries_its_message(self) -> None:
        await self._set_up()
        self._away()
        task = await self._ask_until_posted(_PERMISSION)
        request = self.notifier.posted[0]
        self.relay.answer("T1", "UA", request.id, Outcome(pending.DENY, message="no"))
        reply = await task
        self.assertEqual(reply.body, {"outcome": "deny", "message": "no"})

    async def test_someone_else_cannot_answer(self) -> None:
        await self._set_up()
        self._away()
        task = await self._ask_until_posted(_PERMISSION)
        request = self.notifier.posted[0]
        result = self.relay.answer("T1", "UB", request.id, Outcome(pending.ALLOW))
        self.assertEqual(result, "not_owner")
        self.assertIsNone(self.relay.request_for("T1", "UB", request.id))
        self.assertFalse(task.done())
        self.relay.answer("T1", "UA", request.id, Outcome(pending.DENY))
        self.assertEqual((await task).body, {"outcome": "deny"})

    async def test_a_second_answer_finds_the_request_gone(self) -> None:
        await self._set_up()
        self._away()
        task = await self._ask_until_posted(_PERMISSION)
        request = self.notifier.posted[0]
        self.relay.answer("T1", "UA", request.id, Outcome(pending.ALLOW))
        self.assertEqual(
            self.relay.answer("T1", "UA", request.id, Outcome(pending.DENY)), "gone"
        )
        self.assertEqual((await task).body, {"outcome": "allow"})

    async def test_back_releases_everything_to_the_terminal(self) -> None:
        await self._set_up()
        self._away()
        task = await self._ask_until_posted(_PERMISSION)
        released = self.relay.set_presence("T1", "UA", False)
        self.assertEqual(released, 1)
        reply = await task
        self.assertEqual(reply.status, 204)
        self.assertEqual(self.notifier.closed[0][1].kind, pending.RELEASE)

    async def test_answer_at_terminal_is_a_204(self) -> None:
        await self._set_up()
        self._away()
        task = await self._ask_until_posted(_PERMISSION)
        request = self.notifier.posted[0]
        self.relay.answer("T1", "UA", request.id, Outcome(pending.RELEASE))
        self.assertEqual((await task).status, 204)

    async def test_expiry_releases_and_says_so(self) -> None:
        await self._set_up()
        self._away()
        self.relay.expiry_seconds = 0.05
        reply = await self.relay.ask(self.auth, _PERMISSION)
        self.assertEqual(reply.status, 204)
        self.assertEqual(self.notifier.closed[0][1].actor, "expired")
        self.assertEqual(len(self.relay.registry), 0)

    async def test_a_hook_that_goes_away_closes_its_message(self) -> None:
        await self._set_up()
        self._away()
        task = await self._ask_until_posted(_PERMISSION)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.notifier.closed[0][1].actor, "gone")
        self.assertEqual(len(self.relay.registry), 0)

    async def test_slack_down_fails_open(self) -> None:
        await self._set_up()
        self._away()
        self.relay.notifier = _FakeNotifier(fail=True)
        reply = await self.relay.ask(self.auth, _PERMISSION)
        self.assertEqual(reply.status, 204)
        self.assertEqual(len(self.relay.registry), 0)

    async def test_question_answers_reach_the_hook(self) -> None:
        await self._set_up()
        self._away()
        body = {**_PERMISSION, "kind": "question", "questions": _QUESTIONS}
        task = await self._ask_until_posted(body)
        request = self.notifier.posted[0]
        answers = answers_from_selection(
            request.payload["questions"], {0: [1], 1: [2, 0]}, {}
        )
        assert answers is not None
        self.relay.answer(
            "T1", "UA", request.id, Outcome(pending.ANSWERS, answers=answers)
        )
        reply = await task
        self.assertEqual(
            reply.body,
            {
                "outcome": "answers",
                "answers": {
                    "Which database?": "Postgres",
                    "Which extras?": "cache, auth",
                },
            },
        )

    async def test_allow_on_a_question_is_not_an_answer(self) -> None:
        await self._set_up()
        self._away()
        body = {**_PERMISSION, "kind": "question", "questions": _QUESTIONS}
        task = await self._ask_until_posted(body)
        request = self.notifier.posted[0]
        self.relay.answer("T1", "UA", request.id, Outcome(pending.ALLOW))
        self.assertEqual((await task).status, 204)

    async def test_idle_only_reaches_an_away_developer(self) -> None:
        await self._set_up()
        body = {"session": "s1", "repo": "canon", "message": "waiting"}
        self.assertEqual((await self.relay.idle(self.auth, body)).status, 204)
        self._away()
        self.assertEqual((await self.relay.idle(self.auth, body)).status, 202)
        self.assertEqual(self.notifier.idle[0]["message"], "waiting")
        self.assertEqual((await self.relay.idle("Bearer x", body)).status, 401)


class SelectionTests(unittest.TestCase):
    def test_every_question_needs_an_answer(self) -> None:
        self.assertIsNone(answers_from_selection(_QUESTIONS, {0: [0]}, {}))

    def test_single_select_takes_exactly_one(self) -> None:
        self.assertIsNone(answers_from_selection(_QUESTIONS, {0: [0, 1], 1: [0]}, {}))

    def test_an_index_outside_the_offered_options_is_refused(self) -> None:
        self.assertIsNone(answers_from_selection(_QUESTIONS, {0: [7], 1: [0]}, {}))

    def test_typed_text_wins_over_a_choice(self) -> None:
        answers = answers_from_selection(_QUESTIONS, {0: [0]}, {0: "DuckDB", 1: "none"})
        self.assertEqual(
            answers, {"Which database?": "DuckDB", "Which extras?": "none"}
        )

    def test_duplicate_question_text_is_refused(self) -> None:
        self.assertIsNone(
            clean_questions({"questions": [_QUESTIONS[0], _QUESTIONS[0]]})
        )


if __name__ == "__main__":
    unittest.main()
