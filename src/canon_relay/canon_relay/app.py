# SPDX-License-Identifier: BSD-3-Clause
"""The Slack side: one Bolt app over Socket Mode, owned by the server.

Only glue lives here -- every decision is made in api.py, commands.py and
render.py, which are the Bazel-tested modules. Like canon-mcp's server.py,
this is the one kind of file that imports a third-party SDK, so it is
excluded from Bazel and from pyrefly and is exercised end to end instead
(see plugins/canon-relay/README.md).

Socket Mode means the server opens the connection to Slack, so Slack needs
no public URL of ours. The one bot token and one app token live only in
this process's environment, and no developer ever sees either.
"""

from __future__ import annotations

import re
from typing import Any

from slack_bolt.async_app import AsyncApp

from . import commands, render
from .api import Relay, answers_from_selection
from .pending import ALLOW, ANSWERS, DENY, RELEASE, Outcome, Pending
from .store import Developer


class SlackNotifier:
    """`api.Notifier`, backed by the bot's own Web API client."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def post_request(self, developer: Developer, request: Pending) -> None:
        # Posting to a user ID lands in that user's DM with the app.
        response = await self.client.chat_postMessage(
            channel=developer.slack_user,
            text=render.request_fallback(request),
            blocks=render.request_message(request),
        )
        request.channel = response["channel"]
        request.ts = response["ts"]

    async def close_request(self, request: Pending, outcome: Outcome) -> None:
        if not request.channel or not request.ts:
            return
        await self.client.chat_update(
            channel=request.channel,
            ts=request.ts,
            text=render.request_fallback(request),
            blocks=render.closed_message(request, outcome),
        )

    async def post_idle(self, developer: Developer, payload: dict[str, Any]) -> None:
        repo = payload.get("repo") or "Claude Code"
        await self.client.chat_postMessage(
            channel=developer.slack_user,
            text=f"{repo}: Claude Code is waiting for you",
            blocks=render.idle_message(payload),
        )


def _team(body: dict[str, Any]) -> str:
    team = body.get("team")
    if isinstance(team, dict) and team.get("id"):
        return str(team["id"])
    return str(body.get("team_id") or (body.get("user") or {}).get("team_id") or "")


def _choices(state: dict[str, Any]) -> dict[int, list[int]]:
    """Picked option indexes per question, from a message's `state.values`."""
    choices: dict[int, list[int]] = {}
    for block_id, actions in state.get("values", {}).items():
        match = re.fullmatch(r"q(\d+)", block_id)
        if not match:
            continue
        for value in actions.values():
            options = value.get("selected_options")
            if options is None and value.get("selected_option"):
                options = [value["selected_option"]]
            if options:
                choices[int(match.group(1))] = [
                    int(option["value"]) for option in options
                ]
    return choices


_ENDED = {
    "gone": "That request has already ended.",
    "not_owner": "That request belongs to someone else's session.",
}


def build_app(client: Any, relay: Relay, endpoint: str) -> AsyncApp:
    """The Bolt app, sharing `client` with the `SlackNotifier` inside `relay`."""
    app = AsyncApp(client=client)

    async def publish_home(client: Any, team: str, user: str) -> None:
        developer = relay.store.developer(team, user)
        names = [device.name for device in relay.store.devices(developer.id)]
        await client.views_publish(
            user_id=user, view=render.home_view(developer.away, names)
        )

    async def tell(client: Any, body: dict[str, Any], text: str) -> None:
        channel = (body.get("channel") or {}).get("id") or body["user"]["id"]
        await client.chat_postEphemeral(
            channel=channel, user=body["user"]["id"], text=text
        )

    @app.event("message")
    async def on_message(
        event: dict[str, Any], body: dict[str, Any], client: Any
    ) -> None:
        if (
            event.get("channel_type") != "im"
            or event.get("bot_id")
            or event.get("subtype")
        ):
            return
        team = str(body.get("team_id") or event.get("team") or "")
        result = commands.run(
            relay, team, event["user"], event.get("text", ""), endpoint
        )
        if result.secret:
            await client.chat_postEphemeral(
                channel=event["channel"], user=event["user"], text=result.text
            )
        else:
            await client.chat_postMessage(channel=event["channel"], text=result.text)
        await publish_home(client, team, event["user"])

    @app.command("/canon")
    async def on_command(ack: Any, command: dict[str, Any], client: Any) -> None:
        result = commands.run(
            relay,
            command["team_id"],
            command["user_id"],
            command.get("text", ""),
            endpoint,
        )
        await ack(text=result.text)  # a slash command's reply is ephemeral
        await publish_home(client, command["team_id"], command["user_id"])

    @app.event("app_home_opened")
    async def on_home(event: dict[str, Any], body: dict[str, Any], client: Any) -> None:
        await publish_home(client, str(body.get("team_id") or ""), event["user"])

    async def resolve(body: dict[str, Any], client: Any, outcome: Outcome) -> None:
        request_id = body["actions"][0]["value"]
        result = relay.answer(_team(body), body["user"]["id"], request_id, outcome)
        if result != "ok":
            await tell(client, body, _ENDED[result])

    @app.action(render.ALLOW_ACTION)
    async def on_allow(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        await resolve(body, client, Outcome(ALLOW, actor=body["user"]["id"]))

    @app.action(render.DENY_ACTION)
    async def on_deny(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        await resolve(body, client, Outcome(DENY, actor=body["user"]["id"]))

    @app.action(render.TERMINAL_ACTION)
    async def on_terminal(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        await resolve(body, client, Outcome(RELEASE, actor="terminal"))

    @app.action(render.DENY_REASON_ACTION)
    async def on_deny_reason(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        request_id = body["actions"][0]["value"]
        if relay.request_for(_team(body), body["user"]["id"], request_id) is None:
            await tell(client, body, _ENDED["gone"])
            return
        await client.views_open(
            trigger_id=body["trigger_id"], view=render.deny_reason_modal(request_id)
        )

    @app.view(render.DENY_REASON_VIEW)
    async def on_deny_reason_submit(
        ack: Any, body: dict[str, Any], view: dict[str, Any]
    ) -> None:
        await ack()
        reason = view["state"]["values"][render.REASON_BLOCK][render.REASON_INPUT][
            "value"
        ]
        relay.answer(
            _team(body),
            body["user"]["id"],
            view["private_metadata"],
            Outcome(DENY, message=reason or "", actor=body["user"]["id"]),
        )

    @app.action(re.compile(f"^{render.PICK_ACTION_PREFIX}\\d+$"))
    async def on_pick(ack: Any) -> None:
        await ack()  # selections are read from the message state on Submit

    @app.action(render.SUBMIT_ACTION)
    async def on_submit(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        request_id = body["actions"][0]["value"]
        request = relay.request_for(_team(body), body["user"]["id"], request_id)
        if request is None:
            await tell(client, body, _ENDED["gone"])
            return
        answers = answers_from_selection(
            request.payload["questions"], _choices(body.get("state", {})), {}
        )
        if answers is None:
            await tell(
                client, body, "Answer every question first, or use *Type an answer…*."
            )
            return
        await resolve(
            body, client, Outcome(ANSWERS, answers=answers, actor=body["user"]["id"])
        )

    @app.action(render.TYPE_ACTION)
    async def on_type(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        request_id = body["actions"][0]["value"]
        request = relay.request_for(_team(body), body["user"]["id"], request_id)
        if request is None:
            await tell(client, body, _ENDED["gone"])
            return
        await client.views_open(
            trigger_id=body["trigger_id"], view=render.typed_answer_modal(request)
        )

    @app.view(render.TYPED_ANSWER_VIEW)
    async def on_typed_submit(
        ack: Any, body: dict[str, Any], view: dict[str, Any]
    ) -> None:
        request_id = view["private_metadata"]
        request = relay.request_for(_team(body), body["user"]["id"], request_id)
        if request is None:
            await ack()
            return
        values = view["state"]["values"]
        typed: dict[int, str] = {}
        for index in range(len(request.payload["questions"])):
            block = values.get(f"{render.TYPED_BLOCK_PREFIX}{index}", {})
            typed[index] = (block.get(render.TYPED_INPUT) or {}).get("value") or ""
        answers = answers_from_selection(request.payload["questions"], {}, typed)
        if answers is None:
            missing = {
                f"{render.TYPED_BLOCK_PREFIX}{index}": "Answer this one too."
                for index, text in typed.items()
                if not text.strip()
            }
            await ack(response_action="errors", errors=missing)
            return
        await ack()
        relay.answer(
            _team(body),
            body["user"]["id"],
            request_id,
            Outcome(ANSWERS, answers=answers, actor=body["user"]["id"]),
        )

    @app.action(render.PRESENCE_ACTION)
    async def on_presence(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        away = body["actions"][0]["value"] == "away"
        relay.set_presence(_team(body), body["user"]["id"], away)
        await publish_home(client, _team(body), body["user"]["id"])

    return app
