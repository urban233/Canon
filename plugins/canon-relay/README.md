# canon-relay

An opt-in companion to Canon for **Claude Code**. When you step away from
a local session, the questions it was about to ask you at the terminal
reach your **Slack DM** instead, and your answer goes back to the same
session:

- **Permission prompts**: Allow, Deny, Deny with a reason Claude reads,
  or *Answer at terminal*.
- **`AskUserQuestion`**: pick an option per question, or type an answer.
- **"Waiting for you"**: a note when a session has gone idle waiting for
  your next message.

It is a relay, not a remote control. It only carries a question the
harness was already going to ask, and it only answers with what *you*
chose in Slack. Canon's own gates stay authoritative: anything
`git_guard.py` refuses (merge, force-push, `gh pr merge`, …) is refused
before a permission prompt ever exists, so it never reaches Slack and
cannot be approved from there.

## How it works

```
Claude Code (local)                canon-relay-server (hosted)            Slack
 PermissionRequest ─┐               ┌ POST /v1/ask   (held until answered) ┐
 PreToolUse: Ask…  ─┼─ relay.py ────┤ POST /v1/idle                        ├─ Bolt, Socket Mode ─ your DM
 Notification idle ─┘   (stdlib)    │ sqlite: developers, devices          │
                                    └ pending requests: in memory only     ┘
```

One Slack app, one hosted server, one plugin. Only the server holds the
Slack tokens. Each developer links their machine once and never sees a
Slack secret.

**When it relays is up to you.** DM the bot `away` when you leave and
`back` when you return, or use the toggle in the app's Home tab. While
you're present, every hook call gets an immediate "not relayed" and the
normal terminal prompt appears after one round trip. `back` also sends
anything still waiting in Slack back to your terminal.

**It fails open, always.** If the server is unreachable, the device is
unlinked or revoked, a request expires (after 9 minutes), or anything
else goes wrong, the hook prints nothing. Claude Code then shows its
normal prompt, so the worst case is plain Claude Code.

**What leaves your machine** is the tool's name, a Bash command and its
description (truncated to 500 and 200 characters), a file path or URL,
and for questions the question and option text. Never file contents, an
Edit or Write body, tool output, or the transcript. The server keeps a
request only while a hook is waiting on it and writes none of it to disk.

**Only you can answer your session.** A Slack button carries an opaque
request ID and nothing else. The server checks that the person who
clicked owns the device that asked.

## Set up the Slack app (once per team)

Create an app at <https://api.slack.com/apps> **from a manifest**:

```yaml
display_information:
  name: Canon relay
features:
  app_home:
    home_tab_enabled: true
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: Canon relay
    always_online: true
  slash_commands:
    - command: /canon
      description: Link a machine, or say you're away or back
      usage_hint: "link [name] | devices | revoke <name> | away | back | status"
oauth_config:
  scopes:
    bot:
      - chat:write
      - im:history
      - commands
settings:
  event_subscriptions:
    bot_events:
      - message.im
      - app_home_opened
  interactivity:
    is_enabled: true
  socket_mode_enabled: true
```

Install it to the workspace, then copy the **Bot User OAuth Token**
(`xoxb-…`). Under *Basic Information → App-Level Tokens*, create one with
the `connections:write` scope (`xapp-…`).

## Run the server (once per team)

Python 3.11+ and [`uv`](https://github.com/astral-sh/uv):

```sh
export SLACK_BOT_TOKEN=xoxb-…
export SLACK_APP_TOKEN=xapp-…
export CANON_RELAY_PUBLIC_URL=https://relay.example.org
export CANON_RELAY_DB=/var/lib/canon-relay/relay.sqlite3
uvx --from 'git+https://github.com/urban233/Canon#subdirectory=src/canon_relay' \
    canon-relay-server
```

It listens on `127.0.0.1:8787` by default (`CANON_RELAY_HOST`,
`CANON_RELAY_PORT`). Put it behind a reverse proxy that terminates TLS:
the hook refuses to send its token over plain HTTP to anything but
loopback. Socket Mode means Slack never needs to reach the server, so
only the hook API needs to be reachable, and only by your team. Run it
under whatever supervisor you already use, such as systemd. The SQLite
file holds Slack IDs, device names, token hashes and the away flag, and
nothing else.

## Link your machine (once per machine)

1. DM the bot `link laptop` (or run `/canon link laptop`). It replies,
   visible only to you, with a device token and the endpoint.
2. Install the plugin, and paste both values when Claude Code asks:

   ```
   /plugin marketplace add urban233/Canon
   /plugin install canon-relay@canon
   ```

   To change them later, run `/plugin configure canon-relay@canon`. From a
   shell, `claude plugin install` doesn't prompt, so pass
   `--config endpoint=… --config device_token=…` instead. Claude Code
   keeps the token in your OS credential store, not in `settings.json`.
3. `devices` lists your linked machines, and `revoke <name>` unlinks one.

## Limits, stated plainly

- **Claude Code only.** Codex and Antigravity have no `PermissionRequest`
  hook to carry.
- **Replying in Slack doesn't give the session its next instruction.**
  That would need a `Stop` hook holding the turn open, and Claude Code
  runs every `Stop` hook in parallel. So a relay hook would race Canon's
  own verification gate: a red turn would sit idle until you replied, and
  Slack would already have said the session had finished. See
  [ADR 0009](../../docs/decisions/0009-the-slack-relay-is-an-opt-in-sibling-plugin.md).
- **While you're away, the terminal prompt waits for Slack.** Claude Code
  shows the local prompt only after the hook returns. Say `back`, or press
  *Answer at terminal*, to hand it back straight away.
- **Plan approval (`ExitPlanMode`) is never relayed.** Approving a plan
  from a button without reading it isn't something to make easy.
- One Slack workspace per server, no delegation (only you answer your
  sessions), and no Dockerfile.
