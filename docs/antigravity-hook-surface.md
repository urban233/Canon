# Antigravity hook surface — probe findings

This is the Antigravity equivalent of
[docs/codex-hook-surface.md](codex-hook-surface.md), and it exists for the
same reason: the port needs answers at a precision no prose summary settles,
so they were obtained by running a real Antigravity session against a
throwaway repo and reading what actually came back.

It matters more here than it did for Codex. The first draft of this port was
written against assumed names and assumed events, and three of its central
assumptions were wrong in ways nothing would have reported at runtime — a
hook bound to a deprecated event, an MCP path that could not resolve, and a
reviewer bundled in the wrong directory. A guardrail that silently never
fires is worse than one that is absent, because absence is at least visible.

**Versions used**: Antigravity IDE 2.0 (`/Applications/Antigravity.app`),
CLI `agy` from `~/.gemini/bin/agy`, both as installed on 2026-09-20. The
findings below are pinned to those builds and should be re-checked against a
materially newer release.

## Method

Three independent sources, in descending order of authority:

1. **Live payload capture.** A throwaway plugin (`plugin.json` +
   `hooks.json` + a dump script) was installed with `agy plugin install`,
   and `agy -p "<prompt>" --print-timeout 3m` was run against a throwaway
   git repo. The script wrote each event's raw stdin to a file and answered
   with a minimal valid result. Everything under "Confirmed by capture"
   below is quoted from those files.
2. **`agy plugin validate <path>`**, which reports how many skills, agents,
   commands, MCP servers and hooks it recognises in a plugin directory. This
   is cheap, offline and exact, and it is what settled the `agents/`
   question.
3. **Antigravity's own bundled documentation**, at
   `~/.gemini/antigravity/builtin/skills/agy-customizations/docs/`
   (`hooks.md`, `plugins.md`, `skills.md`, `rules.md`, `mcp_servers.md`,
   `json_configs.md`), plus strings embedded in
   `Contents/Resources/bin/language_server`. Used where capture could not
   reach, and labelled as such.

## Confirmed by capture

### The payload envelope is camelCase; tool arguments are not

Every event's payload carries the same common fields, protojson camelCase as
documented:

```json
{
  "artifactDirectoryPath": "/Users/x/.gemini/antigravity-cli/brain/abc-123",
  "conversationId": "abc-123",
  "modelName": "gemini-3.8-flash-high",
  "transcriptPath": ".../logs/transcript_full.jsonl",
  "workspacePaths": []
}
```

But the `toolCall.args` object inside a `PreToolUse`/`PostToolUse` payload is
**PascalCase**, and its keys are per-tool:

```json
{
  "toolCall": {
    "name": "run_command",
    "args": { "CommandLine": "pwd", "Cwd": "/repo", "WaitMsBeforeAsync": 2000 }
  },
  "stepIdx": 4
}
```

Observed argument sets: `run_command` → `CommandLine`, `Cwd`,
`WaitMsBeforeAsync`; `view_file` → `AbsolutePath`; `write_to_file` →
`TargetFile`, `CodeContent`, `Overwrite`. All three also carry `toolAction`
and `toolSummary`, which are display strings.

This split is the single easiest thing to get wrong, because the documented
sentence "All JSON keys in the hook payloads use camelCase" is true of the
envelope and false of the arguments.

### `workspacePaths` can be empty, and the hook's own cwd is not the repository

In `agy --print` sessions `workspacePaths` came back as `[]` every time.
Meanwhile Antigravity runs a hook with its working directory set to the
directory containing `hooks.json` — which, after `agy plugin install`, is the
plugin's own copied-out directory:

```
CWD=/Users/rootm/.gemini/config/plugins/canonprobe
```

So neither the payload nor the process cwd reliably names the user's
repository. `git rev-parse --show-toplevel`, Canon's usual fallback, would
answer about the plugin directory. This is why
`_common._normalize_antigravity` falls back to the tool call's own `Cwd`
argument, and only when it is absolute.

### `agy plugin install` copies the plugin directory

The probe plugin was installed from a workspace path and landed at
`~/.gemini/config/plugins/canonprobe/` as a copy. This is the same behaviour
Claude Code's and Codex's plugin managers have, and it is the reason
`canon_mcp` is vendored into each plugin rather than referenced through a
sibling `src/` tree that only exists in this monorepo.

### `${PLUGIN_ROOT}` expands in `mcp_config.json`; `${WORKSPACE_ROOT}` does not

With an MCP server configured in a plugin's `mcp_config.json`, the spawned
process reported:

```
CWD=/Users/rootm/.gemini/config/plugins/canonprobe
ARGS=relarg /Users/rootm/.gemini/config/plugins/canonprobe/vendor $PLUGIN_ROOT ${CLAUDE_PLUGIN_ROOT}
PLUGIN_ROOT=/Users/rootm/.gemini/config/plugins/canonprobe
PLUGIN_DATA=/Users/rootm/.gemini/antigravity-cli/plugin_data/canonprobe
```

Four things follow, all of them load-bearing:

- `${PLUGIN_ROOT}` **is** substituted, in both `args` and `env` values.
- The bare `$PLUGIN_ROOT` form is **not**; only `${...}` is.
- `${WORKSPACE_ROOT}` and `${CONVERSATION_ID}` are **not** substituted here,
  though both strings exist in the language server. There is therefore no
  documented way to tell an MCP server which repository it is serving.
- `PLUGIN_ROOT` and `PLUGIN_DATA` are also exported into the server's
  environment.

A **relative `command`** does not resolve at all — `agy plugin validate`
rejects it outright:

```
Error: MCP server "canonprobe" command "./mcpprobe.sh" not found on PATH
```

### A hook's `allow` is not an approval

A `PreToolUse` hook answering `{"decision": "allow"}` did **not** bypass the
permission system: the run still ended with *"a tool required the `command`
permission that headless mode cannot prompt for, so it was auto-denied"*.
Only `permissionOverrides` actually granted anything — adding
`read_file(<path>)` let a previously-denied `view_file` through.

This is what makes it safe for `_common.allow()` to answer `allow` on
Antigravity. Canon may refuse a tool call; it must never quietly approve one
on the user's behalf, and this says it does not.

### `PreInvocation` fires, `PostInvocation` fires

Both were captured, carrying `invocationNum` and `initialNumSteps` alongside
the common fields. `invocationNum` starts at `0`.

## Confirmed by `agy plugin validate`

### `agents/` is a first-class plugin directory, and takes Claude Code's layout

The validator recognises five plugin components: `skills`, `agents`,
`commands`, `mcpServers`, `hooks`. Both of these layouts report
`agents : 1 processed`:

- `agents/<name>.md` — identical to `plugins/claude/agents/reviewer.md`
- `agents/<name>/agent.md`

The flat form is what this port uses, so the Antigravity reviewer brief sits
next to the Claude one in shape as well as content. The language server's own
embedded plugin description agrees: *"**agents/**: A directory containing
subagents that can be invoked to help with tasks related to the plugin."*

The first draft of this port shipped both reviewers as **skills**, which
meant they could be read but not dispatched as independent contexts.

## Confirmed from bundled documentation and binary strings

These could not be reached by capture, and are labelled accordingly.

### `PreInvocation`'s output is ignored

The language server contains the string:

```
Pre-invocation hook %q is deprecated and has no effect
```

The hook still *runs* — it was captured — but its `injectSteps` result does
nothing. The first draft of this port bound Canon's session-context hook
there, which would have run on every turn and injected nothing, reporting no
error. `session_start.py` is bound to `PostInvocation` instead, gated to
`invocationNum == 0`.

Whether `PostInvocation`'s `injectSteps` is itself honoured end-to-end is
**not confirmed** — see "Open questions".

### The `Stop` decision is inverted relative to Claude Code

Per `hooks.md`: `"decision": "continue"` blocks the stop and re-enters the
loop, and *any other value* allows the agent to stop. Claude Code and Codex
spell the same intent `"block"`. Emitting `"block"` here would not error; it
would read as permission to stop, silently defeating the one gate Canon
exists to hold. `_common.block()` handles the inversion, and
`tests/test_antigravity_hooks_dialect.py` asserts it in both directions.

### Event structure is grouped for tool events and flat for the rest

`PreToolUse` and `PostToolUse` take a `matcher` plus a nested `hooks` array.
`PreInvocation`, `PostInvocation` and `Stop` take handler objects directly.
This asymmetry is documented and correct; it looks like an inconsistency in
`hooks.json` and is not one.

### Tool names

`hooks.md` says matcher targets are derived by lowercasing the step type and
dropping the `CORTEX_STEP_TYPE_` prefix. Reading the enum out of the binary
alone is misleading — there is no `CORTEX_STEP_TYPE_REPLACE_FILE_CONTENT`,
yet `replace_file_content` is a real tool. The authoritative list is the
model-facing instruction the language server itself ships:

> When taking actions, always use specialized tools such as `grep_search`,
> `find_by_name`, `view_file`, `write_to_file`, `edit_file`,
> `multi_replace_file_content`, and `list_dir`.

with `replace_file_content`, `run_command`, `invoke_subagent` and
`notebook_edit` appearing in adjacent instruction text. `run_command`,
`view_file` and `write_to_file` are additionally confirmed by capture.

Canon's edit-tool matcher therefore covers `write_to_file`,
`replace_file_content`, `multi_replace_file_content`, `edit_file` and
`notebook_edit`. The first draft matched only the first two, so an edit made
with `edit_file` would have passed the plan gate, the scope check and the
fast check without any of them running.

### Hook timeouts default to 30 seconds

Documented in `hooks.md`. Canon's `stop.py` allows its verify command 300s
and `fast_check.py` allows 60s, so both bindings in `hooks.json` set a
`timeout` above their own — without it the host would kill the hook first.

## What Antigravity does not have

### No `SubagentStop`, so review verdicts are not captured

`hooks.md` lists five events; none fires when a subagent finishes.
`PostToolUse` on `invoke_subagent` would fire, but its documented payload
carries only `stepIdx` and `error` — not the tool's result — so the
subagent's closing verdict is not reachable from a hook.

This is a real weakening of Invariant III on this platform, and it is stated
rather than papered over: `capture_review.py` is vendored into the plugin but
**bound to nothing**, `canon_review` will report no stored verdict, and the
`review` skill instructs the agent to quote the reviewer's own closing line
verbatim and say it was read in-session.

There is a candidate fix — every payload carries `transcriptPath`, so a
`PostToolUse` hook on `invoke_subagent` could read the subagent's final
message out of the transcript — but the transcript's format and whether
subagent output lands in it are unverified, so it is filed as future work
rather than implemented on a guess.

### No reachable host code review

Claude Code's reviewer brief takes its findings from `claude -p
"/code-review"` run as a subprocess. `agy agents` lists no built-in agents
and there is no documented headless entry point to Antigravity's in-IDE
review, so the Antigravity reviewer reads the diff itself — the same position
Codex is in, and the Codex brief is what this port derives from.

### No workspace path for the MCP server

Covered above. `canon-mcp`'s tools resolve their repository from
`CLAUDE_PROJECT_DIR` or the process cwd, and on Antigravity the cwd is the
plugin directory and no variable supplies the workspace. Until that is
solved, the five `canon_*` tools should be treated as unavailable on this
platform. The hooks, skills and reviewer subagents do not depend on them.

## Open questions

Each of these is a thing this port currently assumes, which capture did not
settle. They are tracked in the issue this port opened rather than answered
by guessing.

1. Does `PostInvocation`'s `injectSteps` actually inject? `PreInvocation`'s
   is explicitly dead; `PostInvocation`'s is documented as live but was
   never observed taking effect.
2. Does a `Stop` hook answering `{"decision": "continue"}` re-enter the loop
   in practice? No `Stop` event was captured — the probe turns all ended on
   a permission denial before reaching one.
3. Does `overwrite` on a `PreToolUse` result rewrite the command as
   documented? `git_guard.py` depends on it to strip a `Co-Authored-By`
   trailer.
4. Is `workspacePaths` populated in IDE sessions, as opposed to the `agy
   --print` sessions probed here? If it is, the `Cwd` fallback is belt and
   braces rather than the primary path.
5. Can the subagent transcript be read back to restore verdict capture?
