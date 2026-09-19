# 7. How canon-mcp learns its workspace on Antigravity

Date: 2026-09-20

## Status

Proposed. The measurement is settled; the choice is not, because two of
the three options trade against an invariant and one is deprecated.

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

Not yet taken. What this ADR settles is that the choice is a real one
and must be made deliberately rather than by whichever mechanism someone
reaches for first.

What has been done already is to put the seam in place:
`canon_mcp._git.set_client_root()` records a workspace root from any
source, and `repo_root()` prefers it over every environment guess. Each
option above then becomes a small, isolated change at one call site
rather than a rewrite of five tools.

The recommendation is **A, guarded** -- ask via `roots/list`, but only
when the client has declared the capability, falling back to today's
behaviour otherwise. It is the only option that does not invent a
mechanism or add a question, and the deprecation is survivable because
the seam makes replacing it cheap. It should not be merged without an
end-to-end test against a real IDE session, because the one measurement
available returned an empty list and a guarded resolver that silently
resolves to nothing is indistinguishable from the bug it fixes.

## Consequences

- Until this is decided and tested, `canon_position`, `canon_plan`,
  `canon_review`, `canon_evidence` and `canon_ship` are documented as
  unavailable on Antigravity. Every hook, skill and reviewer subagent
  works without them.
- `set_client_root()` is dead code on Claude Code and Codex, and stays
  that way. It is a seam, not a feature, and it is cheaper than the
  alternative of threading a root through five tool signatures later.
- If A is taken and `roots` is removed from the protocol, the fallback
  is B or C, at the same one call site.
