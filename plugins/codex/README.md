# Canon for Codex

This is Canon's port to [Codex](https://developers.openai.com/codex), OpenAI's
agent CLI. It enforces the same three invariants as the
[Claude Code plugin](../claude) -- a plan persisted where a hook can read it,
a verification gate that re-runs the command rather than trusting the agent's
word, and review that happens in a fresh context -- adapted to what Codex
actually provides. Most of the underlying logic is shared byte-for-byte with
the Claude plugin; see [`src/canon_hooks/`](../../src/canon_hooks) and that
package's own module docstrings for what's shared and why.

**What's genuinely different here, and why**, is documented inline where it
matters: [`hooks/normalize_plan.py`](hooks/normalize_plan.py) (Codex has no
`ExitPlanMode` tool, so plan persistence works the other way around --
the agent writes the file, a hook derives its header), the
[`plan`](skills/plan/SKILL.md) and [`frame`](skills/frame/SKILL.md) skills
(rewritten around that same difference), and the two files under
[`agents/`](agents) (Codex plugins cannot bundle subagents the way Claude
Code plugins can, so these ship as plain files with a manual install step
below). Everything else -- `decide`, `review-change`, `ship`, `testing-craft`,
and six of the seven hooks -- is unchanged in substance.

**The eval suite is Claude-only.** `plugins/claude/evals/` and `just eval`
stay scoped to the Claude plugin; this plugin has no eval suite of its own,
by design -- see [`docs/decisions/0003-eval-suite-is-not-a-ci-gate.md`](../../docs/decisions/0003-eval-suite-is-not-a-ci-gate.md).

## What was empirically confirmed, and what wasn't

This port was written against real `codex exec` output, and the finished
plugin was actually installed and run through the real `codex` CLI -- not
simulated. What that confirmed, and what it explicitly could **not**
confirm, is written up in full in
[`docs/codex-hook-surface.md`](../../docs/codex-hook-surface.md). The short
version:

- The exact `tool_input` shape for an edit's `PreToolUse`/`PostToolUse`
  payload was not confirmed; the hooks extract a touched path defensively
  (see `_common.edited_paths`) rather than assuming one shape.
- The exact `agent_type` value `SubagentStop` reports for a custom subagent
  was not confirmed; `capture_review.py` matches it by substring rather than
  exact equality, and this plugin's own `hooks.json` leaves `SubagentStop`'s
  matcher open (`"*"`) rather than guessing a namespaced form.
- **Every custom MCP server connects intermittently under Codex right
  now, `canon` included -- this is a Codex-side bug, not something wrong
  with this plugin.** Once connected, everything works completely
  correctly -- right tool names, right responses, no protocol issues --
  but the connection itself succeeds only some of the time, and this was
  confirmed to affect even the simplest possible dependency-free test
  server, not anything specific to `canon_mcp`'s packaging. See "MCP
  connectivity is intermittent" below.

The first two are fail-open by construction -- a wrong guess means a gate
goes quiet, never that it blocks something it shouldn't (see `_common.py`'s
module docstring) -- and do not block using this plugin. The third does
occasionally block `canon_position`/`canon_plan`/`canon_review`/`canon_evidence`/
`canon_ship` specifically; the hooks, skills, and reviewer subagents all
function independently of it.

## Requirements

- [Codex CLI](https://developers.openai.com/codex), logged in.
- [`uv`](https://github.com/astral-sh/uv) on `PATH` -- `canon-mcp` runs
  through `uvx`, same as on Claude Code.
- [`gh`](https://cli.github.com), authenticated -- the `ship` skill opens
  pull requests with it.

No checkout of this repository is required just to run `canon-mcp`:
`mcp.json`'s `command` used to resolve it via a path relative to the plugin
root (`${CLAUDE_PLUGIN_ROOT}/../../src/canon_mcp`), which broke the moment
a plugin was actually installed -- both Claude Code's and Codex's plugin
managers copy only the plugin's own directory into a separate cache
location, with no sibling `src/` tree there, so that path resolved to
nothing, deterministically, no matter how the plugin was installed. Fixed
by vendoring `canon_mcp` into [`vendor/canon_mcp/`](vendor/canon_mcp) --
kept in sync with the one canonical copy at
[`src/canon_mcp/`](../../src/canon_mcp) via `just sync-mcp` (see the
[`Justfile`](../../Justfile)) -- and pointing `mcp.json` at that vendored
copy instead. A plugin installed from a remote marketplace now carries a
working `canon-mcp` with it, the same as a local-checkout install does.

## Install

From a checkout of this repository:

```sh
codex plugin marketplace add .
codex plugin add codex@canon
```

(the marketplace manifest lives at
[`.agents/plugins/marketplace.json`](../../.agents/plugins/marketplace.json)
at the repo root -- confirmed against this CLI version to be where a local
marketplace's manifest actually needs to be, not `.claude-plugin/`'s
`.codex-plugin/` analogue, which this port tried first and which Codex
rejects outright.)

[`canon-companion`](../canon-companion) -- the same opt-in code-quality
skills plugin the root README describes for Claude Code -- installs on
Codex from the same marketplace, the same way: `codex plugin add
canon-companion@canon`. It has no hook, MCP server, or bundled subagent, so
none of the install steps below apply to it.

Codex loads a project's own `.codex/` layer -- config, hooks, rules -- only
for a **trusted** project. Mark this checkout trusted the first time you use
it here (via the CLI's own trust prompt, or `-c
projects."<absolute-path-to-this-repo>".trust_level="trusted"`).

**Hook trust is separate from project trust**, and Codex reviews each hook
definition individually before letting it run at all -- use the `/hooks`
command in an interactive session to review and trust this plugin's
`hooks/hooks.json`. Do this once per hook, not per session; a changed hook
(for instance, after `just sync-hooks` picks up a fix from
`src/canon_hooks/`) needs re-review, by design. Never reach for
`--dangerously-bypass-hook-trust` for ordinary use -- it is a one-off
automation escape hatch, not a substitute for reviewing what a hook does.

### The reviewer subagents

Codex plugins cannot bundle a custom subagent the way a Claude Code plugin
bundles [`agents/reviewer.md`](../claude/agents/reviewer.md); a custom agent
is a standalone TOML file Codex discovers under `.codex/agents/`. Copy (or
symlink) both files in:

```sh
mkdir -p .codex/agents
cp plugins/codex/agents/reviewer.toml plugins/codex/agents/risk-reviewer.toml .codex/agents/
```

### MCP connectivity is intermittent -- this is a Codex bug, not a `canon_mcp` problem

This is a genuine Codex-side connection flakiness, separate from -- and
found after fixing -- two packaging bugs that would otherwise have masked
it entirely by making every connection attempt fail the same deterministic
way: `${CLAUDE_PLUGIN_ROOT}` never expanding inside `mcp.json` (below), and
`canon-mcp`'s path resolving to nothing once actually installed through a
marketplace (see "No checkout of this repository is required" above).
With both of those fixed, what's left is real intermittency, not a
packaging mistake dressed up as one.

**Confirmed, not just suspected:** `${CLAUDE_PLUGIN_ROOT}` used to be one
broken piece here -- it never expands inside a plugin's bundled
`mcp.json`, confirmed via `codex mcp get canon` showing the literal,
unresolved token. `mcp.json` has since been fixed to read `$PLUGIN_ROOT` as
a genuine shell environment variable instead (which Codex does set
correctly for the server process). That fix is necessary but not
sufficient: **the connection itself succeeds only *some* of the time,
independent of any packaging choice**, and this session went looking for
whether repackaging `canon_mcp` more simply -- up to and including asking
"would a single compiled binary help?" -- would raise that success rate.
It would not, and here's why: invoking `canon_mcp` with every layer of
indirection removed (no `uv`, no `uvx`, the venv's own Python interpreter
called directly) failed at the same rate as the full `uvx`-based path. And
a trivial, dependency-free test server with no third-party code at all --
the simplest a custom MCP server can possibly get -- fails at that same
rate too, roughly one connection in three. **If the simplest possible
server still fails a third of the time, the bug cannot be about what's
being connected to.** It's inside Codex's own MCP client setup for
project- or plugin-configured servers, full stop -- see
`docs/codex-hook-surface.md` for the three-way comparison that established
this.

When it does connect, everything about it is correct -- right tool names
(`mcp__canon__canon_position`, etc.), right responses, no protocol issues.
When it doesn't, the session either hangs with no error and no subprocess
spawned, or completes normally but simply without the `canon` tools
present. **If a session doesn't see the `canon` tools, or hangs on first
use, that's this bug, not a broken plugin -- retry a fresh session.**
Every hook, skill, and reviewer subagent in this plugin is completely
unaffected by any of this, and there is no configuration change on this
plugin's side expected to fix it -- the fix, if one comes, is a Codex CLI
update.

## Use

Same as the Claude plugin: nothing to configure up front. The first time a
turn would otherwise end unverified, Canon's `Stop` hook asks what command
should pass before a turn ends here, and writes the answer to
`.canon/config.json` once you confirm it.

From there: draft in `/plan` mode as usual. Once you approve a plan, the
`plan` (or `frame`, for a multi-branch feature) skill writes it to
`.canon/plans/<branch>.md` or `.canon/plans/features/<slug>.md`, and
`normalize_plan.py` derives its header the moment that file is written.
Ask to ship when the work is done; `canon_ship`, the reviewer subagent, and
the rest behave exactly as they do on Claude Code.
