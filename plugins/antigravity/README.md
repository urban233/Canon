# Canon for Antigravity

Canon's third plugin, for [Google
Antigravity](https://antigravity.google). Same four primitives as the
Claude Code and Codex plugins -- a `Stop` gate that re-runs the
repository's own verification command, plan persistence, an independent
reviewer subagent, and the `canon-mcp` server -- mapped onto the
customization surface Antigravity actually provides.

The hook logic is not reimplemented here. All eleven hook modules are
vendored byte-for-byte from [`src/canon_hooks/`](../../src/canon_hooks)
by `just sync-hooks`, exactly as the other two plugins are; the only
Antigravity-specific code in Canon is the dialect adapter inside
`_common.py`, which normalizes Antigravity's payload on the way in and
picks the matching result shape on the way out. A bug fixed once is
fixed on all three platforms, and `just sync-check` fails if any
vendored copy drifts.

## What was empirically confirmed, and what wasn't

[`docs/antigravity-hook-surface.md`](../../docs/antigravity-hook-surface.md)
is the probe write-up: what was captured from live `agy` sessions, what
came from `agy plugin validate`, what came from Antigravity's own bundled
documentation, and what is still open. Read it before changing anything
here. Three assumptions in this port's first draft were wrong in ways
nothing reports at runtime, which is why that document exists.

Two measurements matter most, because the plugin would be pointless
without the first and broken without the second:

- **The `Stop` gate holds.** A hook answering `{"decision":
  "continue"}` blocks the stop and re-enters the loop, repeatedly --
  four refusals in one turn were captured. Canon's verification gate is
  real on this platform, not assumed.
- **Fail-open really fails open.** A hook that writes nothing reaches
  Antigravity as "no opinion", which is what `fail_open` and every
  non-matching gate rely on. A bare `{}`, by contrast, is a *refusal
  with no reason* -- which is why `_common.allow()` answers
  `{"decision": "allow"}` explicitly and a test pins it.

## Requirements

- [Antigravity](https://antigravity.google), with its `agy` CLI on `PATH`
  for the install commands below.
- [`uv`](https://github.com/astral-sh/uv) on `PATH` -- `canon-mcp` runs
  through `uvx`, same as on the other two platforms.
- [`gh`](https://cli.github.com), authenticated -- the `ship` skill opens
  pull requests with it.

## Install

From a checkout of this repository:

```sh
agy plugin install ./plugins/antigravity
```

`agy plugin install` **copies** the plugin directory into
`~/.gemini/config/plugins/antigravity/` (confirmed directly), the same way
Claude Code's and Codex's plugin managers do. That is why `canon_mcp` is
vendored into [`vendor/canon_mcp/`](vendor/canon_mcp) rather than
referenced through a sibling `src/` tree that only exists in this
monorepo: after install there is no such tree.

For a project-scoped install instead, copy this directory to
`<project>/.agents/plugins/antigravity/`, or register it from
`<project>/.agents/plugins.json`:

```json
{ "entries": [ { "path": "path/to/plugins/antigravity" } ] }
```

Verify with `agy plugin validate ./plugins/antigravity`, which should
report 7 skills, 2 agents, 1 MCP server and 5 hooks.

To remove a global install: `agy plugin uninstall antigravity`. Whether a
plugin is enabled is recorded in your own `config.json`, never inside the
plugin, so the setting survives reinstalling or updating it.

## What's genuinely different from the Claude plugin

### Review verdicts are not captured, so Invariant III is weaker here

On Claude Code and Codex a `SubagentStop` hook reads the reviewer's own
closing message and `canon_review` hands it back, so what reaches `ship`
is the reviewer's words rather than the main session's retelling.
**Antigravity fires no event when a subagent finishes.** `PostToolUse` on
`invoke_subagent` does fire, but its payload carries only `stepIdx` and
`error` -- not the tool's result.

So `capture_review.py` ships in this plugin but is bound to nothing,
`canon_review` reports no stored verdict, and the `review` skill instead
instructs the agent to quote the reviewer's closing verdict line verbatim
and say it was read in-session. This is a real weakening, stated plainly
rather than papered over. There is a candidate fix -- every payload
carries `transcriptPath` -- but the transcript format is unverified, so it
is tracked as future work rather than implemented on a guess.

### `canon-mcp` now asks the client, and waits on one answer

`canon-mcp` has to know which repository it is answering about. On
Antigravity it cannot learn that from the environment: `mcp_config.json`
substitutes `${PLUGIN_ROOT}` and `${PLUGIN_DATA}` and **no workspace
variable**, and the server is spawned with its working directory set to
the plugin directory, so `git rev-parse` answers about the wrong tree.

So it asks, through the protocol's own `roots/list`. Every tool takes a
`workspace` parameter the model never supplies, filled by a resolver
that asks the client -- but only after checking the client declared the
capability, because the SDK *raises* at one that did not, which would
have turned all five tools into errors on Claude Code. Both arms are
verified end to end by `just check-mcp-roots` against a real server:
a client offering a root gets answers about that root; a client offering
nothing is not asked and does not error.

**What is still unresolved is whether Antigravity populates it.** Its
client advertises `roots` with `listChanged: true`, but answered
`{"roots": []}` in every `agy --print` session measured -- exactly as
`workspacePaths` did. If the IDE populates either, the five tools work
here now. Until someone confirms that in a real IDE session, treat
`canon_position`, `canon_plan`, `canon_review`, `canon_evidence` and
`canon_ship` as unavailable on this platform. Every hook, skill and
reviewer subagent works without them.

The options considered, and why this one, are in
[ADR 0007](../../docs/decisions/0007-how-canon-mcp-learns-its-workspace-on-antigravity.md).
Note that `roots` is deprecated as of protocol revision 2026-07-28, so
this is expected to need replacing; `canon_mcp._git.set_client_root` is
the seam that keeps that a one-call-site change.

### The reviewer reads the diff itself

Claude Code's reviewer brief takes its findings from `claude -p
"/code-review"` run as a subprocess. Antigravity ships no reachable
equivalent -- `agy agents` lists none, and there is no documented headless
entry point to its in-IDE review -- so both briefs under
[`agents/`](agents) are ported from the Codex ones, which are in the same
position: the reviewer reads the diff itself, which is worse but honest.

### Plan mode has no exit tool

Like Codex, Antigravity has no `ExitPlanMode` whose result a hook can
read, so the `plan` and `frame` skills instruct the agent to write the
approved plan itself and a `PostToolUse` hook (`normalize_plan.py`,
shared with Codex) derives the file's header afterwards. A header the
agent wrote itself is overwritten, per docs/plan.md §06.

### It carries no eval cases, on purpose

Canon's eval suite lives with the Claude Code plugin and stays there.
`claude plugin eval` is a Claude Code CLI feature -- it scaffolds the
fixture, runs the turn, applies the graders and supplies the judge model
-- and the cases are written in Claude Code's tool vocabulary. This port
carrying none is complete, not outstanding; see
[ADR 0008](../../docs/decisions/0008-the-eval-suite-belongs-to-the-claude-code-plugin.md).

What keeps this plugin's instruction text trustworthy instead is that
most of it is not its own. `decide`, `review-change`, `ship` and
`testing-craft` are byte-identical to the Claude plugin's copies, which
`just sync-check` enforces, so the Claude suite covers them here
transitively. Only `frame`, `plan`, `review` and the two reviewer briefs
diverge, each for a reason given on this page.

### Session context arrives one step later

Antigravity has no `SessionStart`. Its `PreInvocation` event would be the
natural home, but the language server reports it as *"deprecated and has
no effect"* -- a hook bound there runs and is ignored. `session_start.py`
is bound to `PostInvocation` instead, gated to the first invocation of the
turn.
