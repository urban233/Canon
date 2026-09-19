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
documentation, and the five questions still open. Read it before changing
anything here. Three assumptions in this port's first draft were wrong in
ways nothing reports at runtime, which is why that document exists.

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

### `canon-mcp`'s five tools do not yet work here

Antigravity substitutes `${PLUGIN_ROOT}` in `mcp_config.json`, which is how
the vendored server is found, but it substitutes **no** workspace variable
and spawns the server with its working directory set to the plugin
directory. `canon_position`, `canon_plan`, `canon_review`, `canon_evidence`
and `canon_ship` therefore have no way to learn which repository they are
serving, and should be treated as unavailable on this platform. Every
hook, skill and reviewer subagent works independently of them.

This is the same shape of problem the Codex port has with intermittent MCP
connectivity, and it is recorded the same way: as a known limitation with
its cause named, not as a caveat buried in a comment.

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

### Session context arrives one step later

Antigravity has no `SessionStart`. Its `PreInvocation` event would be the
natural home, but the language server reports it as *"deprecated and has
no effect"* -- a hook bound there runs and is ignored. `session_start.py`
is bound to `PostInvocation` instead, gated to the first invocation of the
turn.
