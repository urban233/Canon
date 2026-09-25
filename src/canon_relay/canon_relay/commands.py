# SPDX-License-Identifier: BSD-3-Clause
"""The words a developer sends the relay bot, in a DM or after `/canon`.

`link [name]`, `devices`, `revoke <name>`, `away`, `back`, `status` and
`help`. Identity is never typed: the Slack team and user come from the
event itself, so `link` binds the new device to whoever Slack says sent
it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .api import Relay

_NAME = re.compile(r"^[A-Za-z0-9._-]{1,40}$")

HELP = (
    "*Canon relay*: when you're away, your local Claude Code sessions ask "
    "you here instead of waiting at the terminal.\n"
    "• `link [name]`: link a machine and get its device token\n"
    "• `devices`: list your linked machines\n"
    "• `revoke <name>`: unlink a machine\n"
    "• `away` / `back`: start or stop relaying (`back` sends anything "
    "still waiting back to your terminal)\n"
    "• `status`: show whether you're away"
)


@dataclass
class Result:
    text: str
    # Shown only to the sender and never kept in the DM history: the one
    # reply that carries a device token.
    secret: bool = False


def run(relay: Relay, team: str, user: str, text: str, endpoint: str = "") -> Result:
    words = text.strip().split()
    if not words:
        return Result(HELP)
    verb, args = words[0].lower(), words[1:]
    store = relay.store
    developer = store.developer(team, user)

    if verb == "link":
        name = args[0] if args else store.next_device_name(developer.id)
        if not _NAME.match(name):
            return Result("A device name is 1-40 letters, digits, `.`, `_` or `-`.")
        token = store.link(developer.id, name)
        if token is None:
            return Result(
                f"You already have a device called `{name}`. "
                f"Pick another name, or `revoke {name}` first."
            )
        where = f"Endpoint: `{endpoint}`\n" if endpoint else ""
        return Result(
            f"Linked *{name}*. This token is shown once. Paste it into Claude "
            "Code with `/plugin configure canon-relay@canon`:\n"
            f"`{token}`\n{where}"
            "Then send me `away` whenever you step away.",
            secret=True,
        )
    if verb == "devices":
        devices = store.devices(developer.id)
        if not devices:
            return Result("No linked devices. Send `link <name>` to link one.")
        return Result("\n".join(f"• `{device.name}`" for device in devices))
    if verb == "revoke":
        if not args:
            return Result("Which one? `revoke <name>`. `devices` lists them.")
        if store.revoke(developer.id, args[0]):
            return Result(f"Revoked `{args[0]}`. Its token no longer works.")
        return Result(f"No device called `{args[0]}`.")
    if verb == "away":
        relay.set_presence(team, user, True)
        return Result("You're away. Your sessions will ask here until you send `back`.")
    if verb == "back":
        released = relay.set_presence(team, user, False)
        tail = (
            f" {released} waiting request(s) went back to your terminal."
            if released
            else ""
        )
        return Result("Welcome back. Prompts stay at your terminal." + tail)
    if verb == "status":
        state = "away" if store.developer(team, user).away else "present"
        count = len(store.devices(developer.id))
        return Result(f"You're *{state}*, with {count} linked device(s).")
    return Result(HELP)
