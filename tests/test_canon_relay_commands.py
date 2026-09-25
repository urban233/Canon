# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_relay/canon_relay/commands.py and render.py."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from canon_relay.api import Relay
from canon_relay.pending import ALLOW, DENY, RELEASE, Outcome, Pending, Registry
from canon_relay.store import Developer, Store

from canon_relay import commands, render


class _NullNotifier:
    async def post_request(self, developer: Developer, request: Pending) -> None:
        pass

    async def close_request(self, request: Pending, outcome: Outcome) -> None:
        pass

    async def post_idle(self, developer: Developer, payload: dict[str, Any]) -> None:
        pass


class CommandTests(unittest.TestCase):
    def _set_up(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "relay.sqlite3")
        self.addCleanup(self.store.close)
        self.relay = Relay(self.store, Registry(), _NullNotifier())

    def _run(self, text: str, user: str = "UA") -> commands.Result:
        return commands.run(self.relay, "T1", user, text, "https://relay.example.org")

    def test_link_returns_a_working_token_as_a_secret(self) -> None:
        self._set_up()
        result = self._run("link laptop")
        self.assertTrue(result.secret)
        token = next(word.strip("`") for word in result.text.split() if "crd_" in word)
        found = self.store.authenticate(token)
        assert found is not None
        self.assertEqual(found[0].name, "laptop")
        self.assertEqual(found[1].slack_user, "UA")
        self.assertIn("https://relay.example.org", result.text)

    def test_link_without_a_name_picks_one(self) -> None:
        self._set_up()
        self.assertIn("device-1", self._run("link").text)
        self.assertIn("device-2", self._run("link").text)

    def test_link_refuses_a_bad_or_taken_name(self) -> None:
        self._set_up()
        self.assertFalse(self._run("link bad/name").secret)
        self._run("link laptop")
        again = self._run("link laptop")
        self.assertFalse(again.secret)
        self.assertIn("already", again.text)

    def test_devices_and_revoke(self) -> None:
        self._set_up()
        self._run("link laptop")
        self.assertIn("laptop", self._run("devices").text)
        self.assertIn("Revoked", self._run("revoke laptop").text)
        self.assertIn("No linked devices", self._run("devices").text)

    def test_devices_are_per_person(self) -> None:
        self._set_up()
        self._run("link laptop", user="UB")
        self.assertIn("No linked devices", self._run("devices").text)
        self.assertIn("No device", self._run("revoke laptop").text)

    def test_away_and_back(self) -> None:
        self._set_up()
        self._run("away")
        self.assertTrue(self.store.developer("T1", "UA").away)
        self.assertIn("away", self._run("status").text)
        self._run("back")
        self.assertFalse(self.store.developer("T1", "UA").away)

    def test_anything_else_is_help(self) -> None:
        self._set_up()
        self.assertEqual(self._run("what").text, commands.HELP)
        self.assertEqual(self._run("").text, commands.HELP)


def _request(kind: str, payload: dict[str, Any]) -> Pending:
    loop = asyncio.new_event_loop()
    try:
        future: asyncio.Future[Outcome] = loop.create_future()
    finally:
        loop.close()
    return Pending("rq_1", 1, kind, payload, future)


class RenderTests(unittest.TestCase):
    def test_permission_buttons_carry_only_the_request_id(self) -> None:
        request = _request(
            "permission",
            {
                "repo": "canon",
                "branch": "b",
                "machine": "m",
                "tool": "Bash",
                "command": "rm -rf <build> && echo ```",
            },
        )
        blocks = render.permission_message(request)
        buttons = blocks[-1]["elements"]
        self.assertEqual({button["value"] for button in buttons}, {"rq_1"})
        self.assertEqual(
            [button["action_id"] for button in buttons],
            [
                render.ALLOW_ACTION,
                render.DENY_ACTION,
                render.DENY_REASON_ACTION,
                render.TERMINAL_ACTION,
            ],
        )
        text = blocks[2]["text"]["text"]
        self.assertIn("&lt;build&gt; &amp;&amp;", text)
        self.assertEqual(text.count("```"), 2)

    def test_question_options_are_indexes(self) -> None:
        request = _request(
            "question",
            {
                "repo": "canon",
                "questions": [
                    {
                        "question": "Q?",
                        "header": "H",
                        "multiSelect": True,
                        "options": [
                            {"label": "a", "description": ""},
                            {"label": "b", "description": "bee"},
                        ],
                    }
                ],
            },
        )
        blocks = render.question_message(request)
        select = next(b for b in blocks if b.get("block_id") == "q0")["elements"][0]
        self.assertEqual(select["type"], "multi_static_select")
        self.assertEqual([option["value"] for option in select["options"]], ["0", "1"])

    def test_closed_message_has_no_buttons_and_says_how_it_ended(self) -> None:
        request = _request("permission", {"repo": "canon", "tool": "Bash"})
        for outcome, phrase in (
            (Outcome(ALLOW), "Allowed"),
            (Outcome(DENY, message="nope"), "nope"),
            (Outcome(RELEASE, actor="expired"), "Expired"),
            (Outcome(RELEASE, actor="gone"), "stopped waiting"),
            (Outcome(RELEASE, actor="back"), "back to your terminal"),
        ):
            blocks = render.closed_message(request, outcome)
            self.assertNotIn('"actions"', json.dumps(blocks))
            self.assertIn(phrase, json.dumps(blocks))

    def test_home_view_offers_the_opposite_state(self) -> None:
        away = json.dumps(render.home_view(True, ["laptop"]))
        present = json.dumps(render.home_view(False, []))
        self.assertIn("I'm back", away)
        self.assertIn("laptop", away)
        self.assertIn("I'm away", present)


if __name__ == "__main__":
    unittest.main()
