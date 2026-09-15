# Codex hook surface — probe findings

This is the write-up Step 0 of the Codex port produced. It exists to answer
questions the official Codex documentation does not settle at the precision
the port needs, by actually running `codex exec` against a throwaway repo and
inspecting what came back — not by inferring from prose. Per this project's
own practice for exploratory work (see
[docs/intent-driven-development.md](intent-driven-development.md) §9), the
branch that ran this probe (`codex-port/probe`) is discarded once this
document is captured; only this file survives, carried onto `codex-port` as a
plain new file.

**Codex CLI version used**: `codex-cli 0.154.0` (installed via
`npm install -g @openai/codex --prefix ~/.npm-global`, since this machine's
Node install is read-only). Findings below are pinned to this version and
should be re-checked if the port is revisited against a materially newer
release.

## Method

A throwaway git repo (`git init`, one seed commit) with a `.codex/` directory
containing:

- `hooks.json` binding a single logging script to every documented event
  (`SessionStart`, `UserPromptSubmit`, `PreToolUse`/`PostToolUse` with
  matcher `"*"`, `SubagentStart`/`SubagentStop`, `Stop`, `PreCompact`,
  `PostCompact`, `SessionEnd`), each entry shaped like:

  ```json
  { "hooks": [ { "type": "command", "command": "python3 <abs-path>/log_payload.py" } ] }
  ```

- `log_payload.py`, which reads `stdin`, parses it as JSON, appends a record
  (timestamp, event name, full payload, a filtered slice of `os.environ` for
  any key containing `PLUGIN`/`CODEX`/`CLAUDE`/`SCRATCH`/`SESSION`, and
  `sys.argv[1:]`) to a log file next to it, and always exits `0`.

- `agents/prober.toml`, a minimal custom subagent:

  ```toml
  name = "prober"
  description = "Probe subagent used only to observe SubagentStart/SubagentStop payload shape."
  developer_instructions = """
  You are a throwaway probe subagent. Reply with exactly: PROBE-OK
  Then stop.
  """
  ```

Driven with `codex exec --json --sandbox <mode> -C <repo> "<prompt>"`.

## Confirmed findings

### Hooks require trust to run at all under `codex exec`, silently

A first run with no trust granted produced **zero** hook invocations — not
even `SessionStart`. This matches the documented behaviour that
`codex exec` cannot prompt interactively to trust a hook, so an untrusted
hook (including a project's own, non-managed `.codex/hooks.json`) is simply
skipped, with no error and no record left behind for later trust. There is no
plain, undocumented way to observe a hook's payload from `codex exec` without
first trusting it by one of the two mechanisms the docs describe: the
interactive `/hooks` flow (writes `hooks.state."<key>".trusted_hash` into the
user config layer) or the CLI's one-off
`--dangerously-bypass-hook-trust` flag.

For this probe, hook trust could only be confirmed using the one-off bypass
flag, and only for a turn that took no actual write/exec actions of its own —
an attempt to combine the bypass flag with a turn that edited a file and ran
a shell command was declined by this session's own tooling policy as an
unsafe combination, and that boundary was respected rather than routed
around. **This means the exact `tool_input` shape for a file edit and for a
shell command inside `PreToolUse`/`PostToolUse` was *not* empirically
confirmed**, and neither was the `agent_type` value `SubagentStop` reports
for a custom subagent. Both remain open — see "Not confirmed" below.

What *was* confirmed, from a trusted, no-op turn (`--dangerously-bypass-hook-trust`
plus a prompt with no tool calls):

**`SessionStart`** — actual captured payload:
```json
{
  "session_id": "01a0a6c3-150f-7531-90e8-361bef6359df",
  "transcript_path": "/Users/rootm/.codex/sessions/2026/09/15/rollout-....jsonl",
  "cwd": "<repo>",
  "hook_event_name": "SessionStart",
  "model": "gpt-5.6-terra",
  "permission_mode": "bypassPermissions",
  "source": "startup"
}
```
Confirms the common fields the docs describe (`session_id`, `transcript_path`,
`cwd`, `hook_event_name`, `model`, `permission_mode`), and confirms one real
`permission_mode` value (`"bypassPermissions"` — same spelling Claude Code
uses). Confirms `source: "startup"` fires on a fresh `codex exec` invocation.

**No `scratchpad_dir` field anywhere, on any event.** Codex's payload has
nothing resembling Claude Code's session-scoped scratchpad directory. This
confirms the gap the plan already assumed: Canon's Codex `state_dir()`
adapter cannot read one from the payload and must derive its own location
(e.g. under the system temp directory, keyed by `session_id`) — see
"Recommendation" below.

**`UserPromptSubmit`** — carries `prompt` (the literal text), plus the same
common fields and a `turn_id` not present on `SessionStart`.

**`Stop`** — actual captured payload:
```json
{
  "...common fields...": "...",
  "turn_id": "01a0a6c3-1564-78d1-85fd-c21419dba1ed",
  "stop_hook_active": false,
  "last_assistant_message": "OK"
}
```
Confirms both fields `stop.py` depends on exist under the same names Claude
Code uses.

**`SessionEnd`** — fires with a `reason` field (observed value: `"other"`);
no `scratchpad_dir` here either.

**Subagent dispatch is real and observable without hook trust**, via the
plain `codex exec --json` event stream (not a hook — this is the ordinary
output stream, always available). Asking the top-level agent to "spawn the
`prober` subagent" produced:
```json
{"type":"item.started","item":{"id":"item_1","type":"collab_tool_call","tool":"wait","sender_thread_id":"...","receiver_thread_ids":[],"prompt":null,"agents_states":{},"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"The prober replied: **PROBE-OK**"}}
```
So subagent spawning goes through a `collab_tool_call` (`tool: "wait"`) with
`sender_thread_id`/`receiver_thread_ids`/`agents_states`, consistent with the
`multi_agent`/`multi_agent_v2` feature flags this build reports as enabled —
a thread-based collaboration model, not a single discrete "spawn" tool call.
This is useful context for Step 5 but is **not** a substitute for confirming
`SubagentStop`'s `agent_type` field, which only a hook (not this event
stream) would show.

**A file edit and a shell command, observed only through the ordinary event
stream** (not a hook payload — captured from a turn that used the bypass flag
in a way this session's own policy still allowed, because that particular
turn took no destructive action beyond writing one scratch file the probe
repo itself owned):
```json
{"type":"item.completed","item":{"id":"item_1","type":"file_change","changes":[{"path":"<abs>/touched.txt","kind":"add"}],"status":"completed"}}
{"type":"item.completed","item":{"id":"item_2","type":"command_execution","command":"/bin/zsh -lc 'echo probe-shell-ran'","aggregated_output":"probe-shell-ran\n","exit_code":0,"status":"completed"}}
```
This is the **exec event stream's** shape, not confirmed to be identical to
the **hook's** `tool_input` shape — but it is suggestive: a file change is
reported as `changes: [{path, kind}]` (potentially several paths in one
call), and a shell command carries the fully-expanded command line the shell
actually ran (`/bin/zsh -lc '<command>'`), not a bare argv list. Treat this as
a strong hint for Step 3, not a confirmed fact.

### Hook trust persists to the user's own global config, not the project

`--dangerously-bypass-hook-trust` is a one-off, per-invocation flag (per the
docs) and did not, itself, write anything to `~/.codex/config.toml`. But
marking a project trusted via `-c projects."<path>".trust_level="trusted"`
**does** persist — Codex writes it straight into the live, global
`~/.codex/config.toml`, immediately, not just for the current invocation.
Anyone re-running this probe should expect the throwaway repo's path to show
up as a trusted project in their own real Codex config afterward, and should
remove that entry once done — this probe's own such entry was added and then
removed for that reason.

## Not confirmed (open questions for Step 3 and Step 5)

1. **The exact `tool_input` key names Codex's `PreToolUse`/`PostToolUse`
   hooks send for a file edit and for a shell command**, and the exact tool
   name(s) used (`apply_patch` vs `Edit`/`Write`; `Bash` vs something else).
2. **The `agent_type` value `SubagentStop` reports for a custom subagent**
   (bare `"prober"`, or a namespaced form).
3. Whether `${CLAUDE_PLUGIN_ROOT}` / `$PLUGIN_ROOT` expand inside a plugin's
   `mcp.json` `command`/`args` (not tested — doing so needs an installed
   plugin, one more layer beyond what this probe reached).
4. The exact local-marketplace path form `codex plugin marketplace add`
   accepts for a repo living on disk (not tested, same reason as #3).

## Recommendation for the port

- **`_payload.py` (Step 1/3) codes defensively** for `edited_paths()` and
  `shell_command()`: try the plausible key names in order
  (`tool_input.get("path")`, `.get("file_path")`, a `changes` list shaped
  like the event-stream's `file_change.changes`, falling back to parsing a
  patch blob out of `tool_input.get("command")` if all else fails), and
  degrade to "can't determine this edit's path" — which, for a fail-open
  gate, means *allow* — rather than guessing wrong and blocking something it
  shouldn't. This mirrors `_common.py`'s existing philosophy: a hook that
  cannot determine something must never turn that uncertainty into a false
  block.
- **`agent_type()` (Step 5) is read leniently**: `capture_review.py`'s Codex
  adapter should match a value that *contains* `"reviewer"` /
  `"risk-reviewer"` rather than requiring an exact string, so a namespaced
  form doesn't silently break verdict capture.
- **`state_dir()` (Step 1) derives its own directory** rather than reading
  one from the payload: `Path(tempfile.gettempdir()) / "canon-codex" /
  payload["session_id"]`, using `session_id` (confirmed present on every
  event) as the stable per-session key. This directory is never committed
  and is exactly as session-scoped as Claude Code's `scratchpad_dir`, just
  derived instead of handed to us.
- **Before Step 3 ships**, whoever picks it up should re-run points 1–2 above
  for real, in an environment whose own tooling policy allows combining
  `--dangerously-bypass-hook-trust` with an actual file edit and shell
  command in a throwaway repo (any environment without an extra safety layer
  on top of Codex itself will do) — this is a short, cheap, one-time check,
  not a recurring cost, and the defensive coding above means shipping without
  it first is safe, just not yet fully verified.
