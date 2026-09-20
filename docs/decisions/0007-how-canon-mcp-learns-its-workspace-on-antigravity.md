# 7. How canon-mcp learns its workspace on Antigravity

Date: 2026-09-20

## Status

Accepted. Option A, guarded, is implemented and tested end to end
against a real server on both arms.

## Context

`canon-mcp`'s five tools all begin by resolving the repository they are
answering about. On Claude Code that is `${CLAUDE_PROJECT_DIR}`,
substituted into `.mcp.json` by the host. On Antigravity there is no
equivalent, and the gap is not cosmetic -- it makes all five tools
unusable on that platform.

Measured directly (see `docs/antigravity-hook-surface.md`):

- An `mcp_config.json` substitutes **`${PLUGIN_ROOT}` and
  `${PLUGIN_DATA}` only**. `${WORKSPACE_ROOT}` and `${CONVERSATION_ID}`
  reach the server as literal strings, in both `args` and `env` values.
- The server is spawned with its working directory set to the **plugin**
  directory, so `git rev-parse --show-toplevel` answers about the wrong
  tree, or about nothing.
- Antigravity's MCP client advertises `roots` with
  `{"listChanged": true}`, and answers `roots/list`. In an `agy --print`
  session it answered `{"roots": []}`.
- Hooks receive **no** `PLUGIN_ROOT` or `PLUGIN_DATA` in their
  environment -- only the MCP server does. A hook's one piece of shared
  ground with the server is its working directory, which is the same
  plugin directory.

So the server cannot infer the workspace, and the two processes that
together know it -- a hook, which receives `workspacePaths`, and the
server, which needs it -- share only one addressable location.

## Options

### A. Ask the client, via the protocol's own `roots/list`

The client is *told* rather than guessed at, and the mechanism is part of
MCP rather than invented here -- it would work on any future host that
implements it, not just this one.

Against it: **`roots` is deprecated as of protocol revision 2026-07-28
(SEP-2577)**, so this builds on something on its way out. It returned an
empty list in the only session that could be measured, and whether the
IDE populates it is unverified. And the SDK's resolver **raises**
`MISSING_REQUIRED_CLIENT_CAPABILITY` when a client does not declare the
capability, so wiring it in carelessly would break Claude Code, where
the tools currently work.

### B. A handshake through the plugin directory

A hook writes the workspace path it already receives to a file under its
working directory; the server reads `${PLUGIN_ROOT}/<that file>`. Both
sides can name that location and nothing else is shared.

Against it: Canon would be writing state. It is outside any repository,
which keeps the letter of "Canon writes no repository state of its own",
and it is the same category as the `Stop` hook's refusal counter --
host-side scratch, never read back to decide anything about the code.
But it is *durable* rather than session-scoped, and it writes into the
installed plugin directory, which may be read-only and which a reinstall
replaces. It is also the option most likely to go stale silently: a
second workspace, or a stale file from a previous project, and the
server answers confidently about the wrong repository. That is precisely
the "wrong-but-plausible is worse than absent" failure docs/plan.md §07
names.

### C. Ask the user, via `elicitation`

The client also advertises `elicitation`, which is not deprecated. The
server could ask once per session which workspace it is serving.

Against it: it puts a question in front of the developer that no other
platform asks, for something the host already knows. Canon asks exactly
one question today (the verify command) and that restraint is load
bearing.

## Decision

**A, guarded.** Every tool takes a `workspace` parameter filled by the
`_workspace_roots` resolver, which asks via `roots/list` -- but only
after checking `ctx.client_capabilities.roots`, degrading to an empty
result otherwise. `canon_mcp._git.adopt_roots()` takes the answer,
records the first `file://` URI naming a directory that exists, and
`repo_root()` prefers it over every environment source.

It is the only option that neither invents a mechanism nor adds a
question the developer does not already answer, and the deprecation is
survivable because `set_client_root()` keeps replacing it a one-call-site
change.

The guard is not a nicety. Without it the SDK raises
`MISSING_REQUIRED_CLIENT_CAPABILITY` at any client that has not declared
`roots`, which would turn all five tools into errors on Claude Code --
fixing the platform where they do not work by breaking the one where
they do.

An empty answer **clears** the recorded root rather than leaving the
previous one. A client that stops offering a workspace must not make the
server answer confidently about a stale repository; that is the
"wrong-but-plausible is worse than absent" rule applied to this seam.

### Verified

`tools/check_mcp_roots.py`, against a real `uvx`-launched server:

- **Arm A** -- a client declaring `roots` and answering with a temp
  repository on branch `feature/from-roots`: `canon_position` reported
  `feature/from-roots`, not the server's own cwd.
- **Arm B** -- a client declaring no capabilities at all: the call
  returned normally, no `MISSING_REQUIRED_CLIENT_CAPABILITY`, falling
  through to the environment sources.

The parsing and policy half (`file://` decoding, skipping a
non-directory, clearing on empty) is covered hermetically in
`tests/test_canon_mcp_git.py::AdoptRootsTests`.

### Still open

Whether Antigravity's client populates `roots/list` with anything. It
answered `{"roots": []}` in every `agy --print` session, exactly as
`workspacePaths` did. If the IDE populates it, `canon-mcp` works there
now; if nothing does, the fallbacks below apply and the tools stay
unavailable on that platform. This is the measurement this change is
waiting on, and it is why the plugin README still lists the tools as
unavailable rather than claiming a fix.

## Consequences

- `canon_position`, `canon_plan`, `canon_review`, `canon_evidence` and
  `canon_ship` now work on **any** host whose MCP client populates
  `roots` -- which is a broader fix than the Antigravity one this began
  as. They remain documented as unavailable on Antigravity until a real
  IDE session shows its client populating them.
- On Claude Code and Codex the resolver returns an empty result and
  nothing changes; `CLAUDE_PROJECT_DIR` still wins as it always did.
  Arm B of `tools/check_mcp_roots.py` is the guard on that.
- When `roots` is eventually removed from the protocol, B or C replaces
  it at the same one call site.
