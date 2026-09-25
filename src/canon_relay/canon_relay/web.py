# SPDX-License-Identifier: BSD-3-Clause
"""The HTTP side the hooks talk to: two POST endpoints and a health check.

Glue only, like app.py -- api.Relay makes every decision -- and excluded
from Bazel and pyrefly for the same reason.

`handler_cancellation=True` is load-bearing. aiohttp stopped cancelling a
handler when its client disconnects (3.9 made that opt-in), and without it
a hook that went away -- answered at the terminal, killed, session ended --
would leave its Slack message live until the request expired.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from .api import Relay, Reply


def _respond(reply: Reply) -> web.Response:
    if reply.body is None:
        return web.Response(status=reply.status)
    return web.json_response(reply.body, status=reply.status)


async def _json(request: web.Request) -> Any:
    try:
        return await request.json()
    except ValueError:
        return None


def build_web_app(relay: Relay) -> web.Application:
    async def ask(request: web.Request) -> web.Response:
        body = await _json(request)
        return _respond(await relay.ask(request.headers.get("Authorization"), body))

    async def idle(request: web.Request) -> web.Response:
        body = await _json(request)
        return _respond(await relay.idle(request.headers.get("Authorization"), body))

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True, "pending": len(relay.registry)})

    application = web.Application(client_max_size=64 * 1024)
    application.add_routes(
        [
            web.post("/v1/ask", ask),
            web.post("/v1/idle", idle),
            web.get("/v1/health", health),
        ]
    )
    return application


async def serve(relay: Relay, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_web_app(relay), handler_cancellation=True)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner
