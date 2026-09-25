# 9. The Slack relay is an opt-in sibling plugin

Date: 2026-09-25

## Status

Accepted.

## Context

A developer running Claude Code locally walks away, and the session then
waits at the terminal on a permission prompt or an `AskUserQuestion`
nobody is there to answer. The goal is to let that session reach its own
developer in a Slack DM and take their answer back. The team shares one
Slack app on one hosted service, and no developer handles a Slack secret.

The Canon plan (docs/plan.md) does not describe this. There, Slack is a
surface Claude Code *runs in*, handled by `async` mode (§09). This is a
different case: a local session reaching out to Slack.

Claude Code already ships two ways to do it. **Remote Control** answers
permission prompts from the Claude mobile app. **Channels** (a research
preview) relays permission prompts through an MCP server, with official
Telegram, Discord and iMessage plugins but none for Slack. Both need more
than a plugin install. Channels is off for a Team or Enterprise
organisation until an admin sets the managed `channelsEnabled` setting.
Remote Control needs a claude.ai-linked account on every machine. The
relay was asked for as an alternative that needs neither.

Three questions had to be settled:

- **Where does it live?** Inside the `claude` plugin, or beside it?
- **When does it relay?** A `PermissionRequest` hook that is waiting on
  Slack holds back the terminal prompt until it returns, for up to its
  600 s timeout. Relaying every prompt would take the terminal prompt away
  from a developer sitting at their desk.
- **Can a Slack reply continue an idle session?** That needs a `Stop` hook
  that holds the turn open until the reply arrives. Claude Code runs every
  matching hook in parallel and waits for all of them. So a relay `Stop`
  hook would race Canon's own verification gate: a red turn would sit idle
  until the developer replied, and Slack would already have told them the
  session had finished. Plugin monitors can't fill the gap either. They
  receive no `userConfig` and no session ID, and what they print reaches
  Claude as an untrusted notification, not as the developer's words.

## Decision

**A third Claude Code plugin in the `canon` marketplace, `canon-relay`, like
`canon-companion`.** It isn't part of the `claude` plugin. Core Canon keeps
every claim it makes: its MCP server owns no database, it adds no surface
to babysit, and it runs identically on three platforms. The relay is
Claude Code only, because neither Codex nor Antigravity documents a
`PermissionRequest` hook. Its hook is stdlib-only Python and reuses
Canon's `_common.py` (vendored by `just sync-hooks`). Its server,
`canon-relay-server`, is a Python package run with `uvx`, and its stdlib
core is Bazel-tested the way `canon_mcp_lib` is. The Slack and HTTP glue
stays outside Bazel and pyrefly, the same line `canon_mcp/server.py` draws.

**Presence is a fact about the developer, kept on the server.** The
developer says `away` or `back` in Slack. While they're present, the
server answers the hook with a `204` straight away, and the terminal
prompt appears after one round trip. This adds no session state to
Canon: the one exception the invariants allow, the `Stop` counter, stays
the only one. The device token lives in Claude Code's own plugin
`userConfig`, in the OS credential store, so Canon writes no credential
file either.

**Pending requests exist only in memory**, each one tied to the hook
connection waiting on it. A restart drops them all, and every waiting
hook falls back to the local prompt. A stale approval therefore can't
outlive the question it answered.

**The relay may approve, but only on an explicit human answer.**
`_common.allow` says Canon "must never quietly approve [a tool call] on
the user's behalf". The relay's `allow` isn't quiet: it's the button the
developer pressed, checked against the Slack identity that owns the
device. Canon's gates still run first. `git_guard.py` refuses at
`PreToolUse`, before a permission prompt exists, so a refused command
never reaches Slack.

**Reply-to-continue is deferred.** The only correct ordering puts it
after Canon's `Stop` gate has decided the turn may end, and only
`stop.py` knows that. The candidate is a small, generic continuation step
inside `stop.py`, which changes core Canon and is a separate decision.

## Consequences

- Installing Canon never brings a network dependency. A team that wants
  the relay opts in, hosts one process, and creates one Slack app.
- Every failure is silence, so the relay can never block work: an
  unreachable server, a revoked device, an expiry, or a malformed reply
  each end in Claude Code's own prompt.
- The Slack message shows a redacted view: tool name, a truncated Bash
  command, a path or URL. Never file contents, an Edit/Write body, tool
  output, or the transcript. A decision that needs the diff has to be
  taken at the terminal, and that is deliberate.
- While the developer is away, their terminal prompt waits for Slack.
  `back` or *Answer at terminal* hands it back immediately, and expiry
  after 540 s hands it back on its own.
- A `PreToolUse` hook's reason (a Canon `ask`) is not part of
  `PermissionRequest`'s input, so the Slack message can't show why Canon
  asked. It shows the tool call itself.
- A later reply-to-continue step touches `stop.py`, so it inherits every
  obligation a core change carries, including the three-platform shared
  hook core.
