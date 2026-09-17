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

## Part 2: installing and running the built plugin for real (Steps 2, 6, 7)

Everything above came from the original `codex-port/probe` branch, before
`plugins/codex/` existed. Once the plugin, its manifests, and its MCP
wiring were actually built, they were installed and driven for real against
the live `codex` CLI on this same machine — not simulated. These findings
supersede the two "not tested" items the first pass left open for the
marketplace and `mcp.json`, and surface one significant new problem.

### The marketplace manifest belongs at `.agents/plugins/marketplace.json`, not `.codex-plugin/marketplace.json`

`codex plugin marketplace add ./.codex-plugin` (this repo's first guess,
mirroring Claude Code's `.claude-plugin/` convention) failed outright:
`Error: invalid marketplace file ...: marketplace root does not contain a
supported manifest`. Comparing against this machine's own real, installed
marketplaces (`codex plugin marketplace list`, then reading
`~/.codex/.tmp/bundled-marketplaces/openai-bundled/.agents/plugins/marketplace.json`
directly) showed the actual convention: the manifest lives at
`<marketplace-root>/.agents/plugins/marketplace.json`, and `codex plugin
marketplace add <root>` is pointed at the root directory, not at the
manifest's own containing directory. This repo's marketplace file moved to
[`.agents/plugins/marketplace.json`](../.agents/plugins/marketplace.json)
at the repo root accordingly, and `codex plugin marketplace add .` (from the
repo root) now succeeds and lists `codex@canon` correctly.

The per-plugin entry schema this port had guessed from the official docs
(`{"name", "source": {"source": "local", "path": "./plugins/<name>"}}`) was
confirmed correct by the same comparison -- only the manifest's *location*
was wrong.

### `plugin.json`'s own `name` must match the marketplace entry's name, exactly

`codex plugin add codex@canon` initially failed: `plugin.json name "canon"
does not match marketplace plugin name "codex"`. Claude Code tolerates this
mismatch (`plugins/claude/.claude-plugin/plugin.json`'s own `name` is
`"canon"`, while the marketplace lists it as `"claude"`), but Codex enforces
it strictly. `plugins/codex/plugin.json`'s `name` field was changed to
`"codex"` to match; after that, `codex plugin add codex@canon` installed
cleanly, copying `hooks/`, `skills/`, `agents/`, `mcp.json`, and `plugin.json`
into `~/.codex/plugins/cache/canon/codex/0.0.1/` and enabling the plugin.

One incidental observation: the installed plugin's cache **did** include the
`agents/` directory verbatim, even though nothing in the documentation
describes plugins bundling subagents. Whether Codex does anything with that
copy (versus treating it as an opaque, unused directory) was not tested --
this port still ships the reviewer briefs as documented, manually-installed
`.codex/agents/*.toml` files (see [`plugins/codex/README.md`](../plugins/codex/README.md)),
since a directory merely being copied into the cache is not evidence it is
read as a subagent definition.

### `${CLAUDE_PLUGIN_ROOT}` does **not** expand in a plugin's bundled `mcp.json` -- confirmed, not just suspected

`codex mcp get canon` (after installing the plugin) showed the server's
`args` verbatim as `--from ${CLAUDE_PLUGIN_ROOT}/../../src/canon_mcp
canon-mcp` -- the literal, unexpanded token, not a resolved path. Its `env`
column did show `PLUGIN_ROOT` and `PLUGIN_DATA` as real environment
variables set for the server process (confirming the hooks docs' claim
about those two names extends to MCP servers too), but no amount of
`${...}`-style templating in `command`/`args` was expanded before the
process launched.

**`plugins/codex/mcp.json` now uses a shell wrapper that reads
`$PLUGIN_ROOT` as a genuine environment variable at runtime** --
`"command": "sh", "args": ["-c", "UV_OFFLINE=1 exec uvx --from \"$PLUGIN_ROOT/../../src/canon_mcp\" canon-mcp"]`
-- instead of the non-functional `${CLAUDE_PLUGIN_ROOT}` template. This is
strictly better than what it replaced (which could never have worked): the
command Codex actually launches is now correct. Whether a given attempt to
*use* it connects in time is a separate, unrelated question -- see the next
section, which found the intermittency is not particular to this exact
form, `uvx`, or `canon_mcp` at all.

### The `canon` MCP server connects intermittently -- and so does everything else. This is a Codex-side bug, not a `canon_mcp` packaging problem.

A first pass (written up in an earlier revision of this section) found the
server simply never responding, for tens of seconds to over two minutes,
with zero evidence -- no subprocess, no log line, nothing -- that Codex had
even tried to spawn it. A second, more instrumented pass (still using the
same project-level `.codex/config.toml` registration, the project marked
trusted the same way hook trust requires: Codex silently skips a project's
entire `.codex/` layer, config included, for an untrusted project) narrowed
this considerably, and a third pass -- prompted by asking "would deploying
`canon_mcp` as a single binary help?" -- settled the question of *where*
the bug actually lives:

- **`canon_mcp`'s own stdio server is protocol-correct and fast, confirmed
  against Codex's exact handshake.** A raw MCP `initialize` request sent by
  hand, using the identical `protocolVersion` (`"2025-06-18"`),
  `capabilities`, and `clientInfo` a real Codex session sends, got a
  correct response from `canon_mcp` in under a second, followed by a
  correct `tools/list` response naming all five tools. This rules out a
  protocol-version mismatch or any other incompatibility in `canon_mcp`
  itself.
- **Removing every layer between Codex and `canon_mcp`'s actual code --
  no `uv`, no `uvx`, no shell wrapper, just the venv's own `python`
  interpreter invoked directly with `-c "from canon_mcp.server import
  main; main()"` -- did not fix it.** Three tries: one full success (all
  five tools listed correctly), one hang (zero subprocess spawned, same
  as the `uvx`-based failures), one turn that completed normally but
  without the tools. This is indistinguishable from `uvx`'s own failure
  rate, and it directly refutes the natural hypothesis that `uv`'s
  dependency-resolution overhead, or the extra `sh`→`uv`→`python`
  process chain, was the cause.
- **The real control case -- a trivial, dependency-free, single-process
  Python stdio server with no third-party imports at all -- fails at
  the same rate.** An earlier revision of this section reported this
  server "connected instantly, every time it was tried," but that claim
  rested on a single successful trial. Retested three more times under
  identical conditions: two successes, one clean failure (no hang, the
  turn simply completed without the tool present) -- the same
  roughly-one-third-to-one-half failure rate `canon_mcp` itself shows,
  not the "always works" result the first trial suggested. **This is the
  decisive finding**: if the simplest possible custom MCP server,
  requiring no dependency resolution, no network, and no process chain
  beyond a bare `python3 <script>`, still fails intermittently, the
  intermittency cannot be about what's being connected to at all. It is
  a property of Codex's own MCP client setup for project/plugin-configured
  servers in general.
- **Renaming the server (`canon` → `canonx`) changed nothing** about the
  intermittent pattern either, ruling out any state cached against that
  specific name.
- **`UV_OFFLINE=1`** (skipping `uv`'s network-touching resolution step)
  had looked like a real improvement in an earlier, smaller round of
  testing. In light of the fake-server result above, that apparent
  improvement is better explained as noise in a roughly one-third-to-
  one-half base failure rate than as a genuine fix -- a handful of trials
  either side of a coin-flip-ish rate will look like a trend by chance
  as often as not.

**Answering "would a single binary help": no, almost certainly not.**
A compiled/frozen single-file executable would remove the same
`uv`/process-chain overhead the direct-`python -c` test already removed,
and that test showed no improvement over `uvx` -- and even *that* wasn't
the floor, since the dependency-free fake server (as simple as an MCP
server can be) shows the identical failure rate. There is no simpler
target to package down to that this session's own evidence didn't already
test and find equally affected. The bug is upstream of anything this
plugin controls.

Put together: this is a **race condition or resource-contention bug in
Codex's own MCP client setup** for project- or plugin-configured servers,
striking at a roughly constant rate regardless of server complexity,
language, or dependency footprint. Roughly a third to a half of connection
attempts either hang outright (zero subprocess spawned -- the block
happens before Codex even execs the configured command) or complete the
turn normally without the server's tools ever appearing.

**Recommendation:** (1) if a session doesn't show the expected MCP tools,
or hangs on first use, retry a fresh `codex exec` invocation -- this is
usually transient, not a broken configuration; (2) do not invest further
effort in `canon_mcp`'s own packaging (single binary, vendored
dependencies, a leaner startup path) expecting it to raise the connection
success rate -- this session's evidence says it won't, because the
simplest possible alternative already shows the same rate; (3) this is
worth reporting upstream as a Codex CLI reliability bug in its MCP client,
with this write-up's three-way comparison (`canon_mcp` via `uvx`,
`canon_mcp` via direct interpreter invocation, and a dependency-free fake
server -- all showing the same intermittent rate) as the reproducer,
since it isolates the bug away from anything server-specific.

None of this blocks shipping the rest of the port: every hook, skill, and
reviewer agent functions independently of whether `canon-mcp` answers, and
the MCP tools now work completely correctly *when* the connection
succeeds -- correct tool names, correct responses, no protocol issues.
What's unresolved is purely the connection's reliability under Codex, not
its correctness once established, and not anything about how `canon_mcp`
is packaged or deployed. `canon_position`, `canon_plan`, `canon_review`,
`canon_evidence`, and `canon_ship` should be expected to work most of the
time and occasionally require a retry, not to be categorically broken.

## Part 3: a real, deterministic packaging bug this investigation had missed

Everything in the section above was about connection *reliability* once
`canon_mcp`'s path resolves to something real. A later session, writing the
root README's install instructions, found that it hadn't -- for anyone
actually installing this plugin the documented way.

**`codex plugin add` and `claude plugin install` both copy only the
plugin's own directory into a separate cache location** --
`~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/` and
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` respectively --
confirmed by installing both plugins for real from this exact checkout and
listing the resulting cache directories. Neither copy includes a sibling
`src/` tree. `mcp.json`'s `$PLUGIN_ROOT/../../src/canon_mcp` (and the
Claude plugin's identical `${CLAUDE_PLUGIN_ROOT}/../../src/canon_mcp`)
therefore resolved to a path that never existed in either cache, for
*any* install method -- local marketplace or remote, checkout-based or
not. Running the exact resolved command by hand, with `$PLUGIN_ROOT` set
to the real cache path, reproduced this deterministically: an immediate
`Distribution not found` error, every time, not intermittently.

This is a different failure mode from the connection flakiness documented
above, and it explains why that earlier investigation didn't catch it:
testing a `uvx`-based invocation, a direct-interpreter invocation, and a
dependency-free fake server all still used paths that pointed at a real
`src/canon_mcp` (this monorepo checkout, not an installed plugin's cache
copy), so all three sidestepped this bug entirely. The intermittency
finding stands on its own terms -- it is real, and it is Codex-side -- but
it was never actually tested against a plugin installed the way this
README tells a user to install it.

**Fixed by vendoring**, the same way `src/canon_hooks` is vendored into
each plugin's `hooks/` directory: `just sync-mcp` copies
`src/canon_mcp/{pyproject.toml,canon_mcp/}` into
`plugins/claude/vendor/canon_mcp/` and `plugins/codex/vendor/canon_mcp/`,
and both `.mcp.json`/`mcp.json` now read `.../vendor/canon_mcp` instead of
reaching outside the plugin. Reinstalling both plugins for real from this
checkout afterward, and running each platform's exact `mcp.json` command
against the real installed cache path, confirmed `canon-mcp` now builds
and answers a real MCP `initialize` correctly from *both* cache
directories. `just sync-check` fails if either vendored copy drifts from
`src/canon_mcp`.

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

## Part 4: `plugins/codex/plugin.json` vs. `plugins/codex/.codex-plugin/plugin.json` — settled empirically

The release-packaging branch found `plugins/codex/plugin.json` (at the
plugin's root) and `plugins/codex/.codex-plugin/plugin.json` byte-identical,
with no record of which one `codex plugin add` actually reads. This was
settled by mutating each copy in turn against a real `codex plugin add
codex@canon` from this checkout (marketplace added via `codex plugin
marketplace add .`), not inferred from the docs or from Claude Code's
`.claude-plugin`/`.claude-plugin` convention:

- **Either file alone is sufficient.** With only `.codex-plugin/plugin.json`
  present (root renamed away), install succeeded and the installed cache
  carried just that file. With only the root `plugin.json` present
  (`.codex-plugin/plugin.json` renamed away instead), install also
  succeeded, cache carrying just the root file. Neither location is
  required by itself.
- **When both are present, the root `plugin.json` is the one Codex
  actually validates and uses; `.codex-plugin/plugin.json` is ignored.**
  Confirmed by giving the two copies different `name` fields and watching
  which one Codex checks against the marketplace entry's name (the same
  check `docs/codex-hook-surface.md` Part 2 already documented as strict
  under Codex, unlike Claude Code): with the root copy's `name` matching
  the marketplace entry (`codex`) and `.codex-plugin/plugin.json`'s `name`
  deliberately mismatched, `codex plugin add codex@canon` **succeeded**
  — proving the mismatched `.codex-plugin` copy was never read. Flipping
  it — root mismatched, `.codex-plugin/plugin.json` matching — made the
  same command **fail** with `plugin.json name "..." does not match
  marketplace plugin name "codex"`, naming the root file's value in the
  error. This is decisive: when both exist, Codex reads the root file and
  the `.codex-plugin` copy is inert, not merely untested.

**Resolution:** `plugins/codex/.codex-plugin/plugin.json` was deleted;
`plugins/codex/plugin.json` (root) is the sole, load-bearing manifest for
this plugin. This is specific to `plugins/codex`'s own layout, where a
root-level `plugin.json` already existed before `.codex-plugin/` was ever
added (see Part 2's install history above) — it does not contradict the
convention every real OpenAI-shipped skills-only plugin on this machine
uses (`.codex-plugin/plugin.json` only, no root copy at all, confirmed
against `~/.codex/plugins/cache/openai-curated-remote/plugin-management`
and `openai-bundled/visualize`), which is why `plugins/canon-companion`'s
new Codex manifest (added by this same branch) is placed at
`.codex-plugin/plugin.json` with no root copy, matching that convention
exactly rather than mirroring `plugins/codex`'s now-resolved duplicate.

**The alternative this evidence also supports, and why it wasn't taken:**
"either file alone is sufficient" cuts both ways — it would have been just
as defensible to move `plugins/codex`'s manifest *into* `.codex-plugin/`
instead, making every plugin in this repo use one convention
(`.codex-plugin/plugin.json` only, matching every real OpenAI-shipped
plugin). That was not done here because `plugins/codex/plugin.json` at
root is the copy every other file in this plugin — `docs/codex-hook-surface.md`
Part 2's install history, this repo's own muscle memory for where to look
— already points at, and moving it buys convention-uniformity at the cost
of a rename that touches nothing functionally broken. Recorded here as a
live option, not a closed question: whoever finds a second reason to
prefer the OpenAI-wide convention should not have to redo this
investigation to justify moving it.

## Part 5: does canon-companion's `skills` key actually matter for skill discovery?

The release-packaging branch's `sync-manifests` generator adds `"skills":
"./skills/"` to canon-companion's Codex manifest, calling it "the key
every OpenAI-shipped skills plugin declares" — a description, not a claim
that Codex requires it. That distinction was checked empirically, using
`codex debug prompt-input` (a genuinely free, local, no-model-call command
that renders the exact prompt input a session would send, including the
full skills list Codex discovered) rather than by running a real session:

- With canon-companion installed (its manifest **carrying** the `skills`
  key), `codex debug prompt-input` listed
  `canon-companion:audit-google-python-style` in the model-visible skills
  list, at its real installed-cache path.
- With canon-companion removed and `codex@canon` installed instead —
  `plugins/codex/plugin.json` ships seven skills and has **no `skills`
  key at all** — all seven (`codex:decide`, `codex:frame`, `codex:plan`,
  `codex:review`, `codex:review-change`, `codex:ship`,
  `codex:testing-craft`) were listed too, identically discoverable.

**Conclusion: the `skills` key is not required for discovery when skills
live at the default `./skills/` path**, which every plugin in this repo
does. `plugins/codex` is not shipping seven undiscoverable skills at
0.1.0 — that specific release risk is ruled out by this test, not merely
assumed safe. What the key is actually *for* (an explicit override for a
non-default skills path, forward-compatibility, or purely documentary)
remains unconfirmed; this session did not find anything in the CLI's own
help output or behavior that pinned down its purpose beyond "every real
example declares it." canon-companion's manifest keeps declaring it
regardless, matching every other real installed example on this machine —
harmless if inert, and one less way this plugin's manifest looks
different from a normal one.

Same install/removal discipline as elsewhere in this doc: `~/.codex/config.toml`
was checksummed before either install, and confirmed byte-identical to
that checksum after both plugins and the `canon` marketplace were removed
again.

## Part 6: `codex plugin add canon-companion@canon` — the plan's `## Done` criterion, confirmed

Everything above in Part 4 confirmed the `plugins/codex` manifest
question; this is the separate, and newer, claim: that canon-companion —
previously Claude-only by omission — actually installs on Codex. Run for
real from this checkout (`codex plugin marketplace add .` then `codex
plugin add canon-companion@canon`):

- The command reported success (`Added plugin canon-companion from
  marketplace canon`) and installed to
  `~/.codex/plugins/cache/canon/canon-companion/0.0.1/`.
- The installed cache directory carried the generated
  `.codex-plugin/plugin.json` (read correctly — see Part 5's discovery
  test, which used this exact installed copy) alongside the untouched
  `.claude-plugin/plugin.json`, `skills/audit-google-python-style/SKILL.md`,
  and the plugin's other files (BUILD.bazel, evals/, references/,
  scripts/) copied verbatim.
- `codex plugin list` reported `canon-companion@canon` as `installed,
  enabled`.
- Part 5's `codex debug prompt-input` run against this exact installed
  copy is what confirmed the skill is in the model-visible skills list,
  not just present as a file in the cache.

**What this does not confirm:** no live, real `codex exec`/interactive
session was run asking the model to actually invoke
`$audit-google-python-style`. The cache contents, the enabled status, and
the model-visible skills list are all confirmed directly against the real
CLI; whether a session in practice picks the skill and completes the
workflow correctly was not exercised, and is a smaller, cheaper gap than
"does it install at all" was before this branch.
