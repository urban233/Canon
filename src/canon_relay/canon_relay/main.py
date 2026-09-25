# SPDX-License-Identifier: BSD-3-Clause
"""`canon-relay-server`: the one hosted process the whole team shares.

    uvx --from 'git+https://github.com/urban233/Canon#subdirectory=src/canon_relay' \\
        canon-relay-server

Configuration is environment only:

- `SLACK_BOT_TOKEN` (`xoxb-…`) and `SLACK_APP_TOKEN` (`xapp-…`, Socket
  Mode), required. They never leave this process.
- `CANON_RELAY_DB`: SQLite path, default `canon-relay.sqlite3`.
- `CANON_RELAY_HOST` / `CANON_RELAY_PORT`: where the hook API listens,
  default `127.0.0.1:8787`. Bind to loopback and let the host's reverse
  proxy terminate TLS -- the hooks refuse to send a token over plain HTTP
  to anything but loopback.
- `CANON_RELAY_PUBLIC_URL`: the HTTPS URL developers paste as the
  plugin's endpoint, echoed back by `link`.
- `CANON_RELAY_EXPIRY_SECONDS`: how long a request waits, default 540.
"""

from __future__ import annotations

import asyncio
import os
import sys

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from .api import DEFAULT_EXPIRY_SECONDS, Relay
from .app import SlackNotifier, build_app
from .pending import Registry
from .store import Store
from .web import serve


async def _run() -> None:
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    if not bot_token or not app_token:
        sys.exit("canon-relay-server: set SLACK_BOT_TOKEN and SLACK_APP_TOKEN")
    store = Store(os.environ.get("CANON_RELAY_DB", "canon-relay.sqlite3"))
    expiry = float(os.environ.get("CANON_RELAY_EXPIRY_SECONDS", DEFAULT_EXPIRY_SECONDS))
    endpoint = os.environ.get("CANON_RELAY_PUBLIC_URL", "")

    client = AsyncWebClient(token=bot_token)
    relay = Relay(store, Registry(), SlackNotifier(client), expiry_seconds=expiry)
    app = build_app(client, relay, endpoint)

    runner = await serve(
        relay,
        os.environ.get("CANON_RELAY_HOST", "127.0.0.1"),
        int(os.environ.get("CANON_RELAY_PORT", "8787")),
    )
    try:
        await AsyncSocketModeHandler(app, app_token).start_async()
    finally:
        await runner.cleanup()
        store.close()


def main() -> None:
    asyncio.run(_run())
