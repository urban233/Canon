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
- **The `canon` MCP server connects intermittently, not reliably.** Once
  connected it works completely correctly -- right tool names, right
  responses, no protocol issues -- but the connection itself sometimes
  hangs rather than completing. See "MCP connectivity is intermittent"
  below for the full investigation and what narrows it down.

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
- A checkout of this repository. `mcp.json`'s `command` resolves
  `canon-mcp` via a path relative to the plugin root
  (`${CLAUDE_PLUGIN_ROOT}/../../src/canon_mcp`), which only exists inside
  this repo's own checkout, not a marketplace-only install of just
  `plugins/codex`. See [`src/canon_mcp/`](../../src/canon_mcp)'s own
  `pyproject.toml` if you want to package it separately.

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

### MCP connectivity is intermittent

**Confirmed, not just suspected:** `${CLAUDE_PLUGIN_ROOT}` does not expand
inside a plugin's bundled `mcp.json` -- `codex mcp get canon` shows the
literal, unresolved token in `args` after installing this plugin. Replacing
it with a project-level `.codex/config.toml` entry using a real, absolute
path fixes that, but exposed a second, deeper issue: the connection itself
succeeds only *some* of the time. When it does, everything about it is
correct -- right tool names (`mcp__canon__canon_position`, etc.), right
responses, no protocol issues, confirmed by sending Codex's exact handshake
directly to `canon_mcp` and by watching a trivial hand-written test server
connect instantly and reliably every time it was tried. When it doesn't,
the session hangs with no error, no subprocess even spawned, until you kill
it and try again. Setting `UV_OFFLINE=1` (below) roughly doubles the odds
of a fast, clean connection but does not make it fully reliable. The
leading hypothesis is a race condition inside Codex's own MCP client setup,
not anything specific to `canon_mcp` -- see `docs/codex-hook-surface.md`'s
"Part 2" section for the full investigation, including everything this
ruled out (protocol version, server naming, trust). **If a session hangs
on first use, that's this issue, not a broken plugin -- kill it and start
a fresh one.** Every hook, skill, and reviewer subagent in this plugin is
completely unaffected by any of this.

Register the server directly in this repository's own `.codex/config.toml`
(remember: the project must be marked **trusted** first, or Codex silently
ignores this file too -- see above) rather than relying on the plugin's own
`mcp.json`, and force `uv` to skip network resolution to improve your odds
of a clean connection:

```toml
[mcp_servers.canon]
command = "sh"
args = ["-c", "UV_OFFLINE=1 exec uvx --from /absolute/path/to/this/checkout/src/canon_mcp canon-mcp"]
default_tools_approval_mode = "auto"
```

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
