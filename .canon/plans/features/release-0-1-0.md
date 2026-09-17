---
status: approved
steps:
---

# Release 0.1.0

What stands between Canon as it sits on `main` today and a first public
version, closed in four branch-sized steps. Two are correctness bugs
that undermine invariants Canon advertises in its own README; one is
packaging, including the companion plugin's missing Codex support; the
last is the release itself. Found by reading the shipped tree against
the README's claims, and against the real Codex plugin cache on this
machine rather than against Codex's documentation.

## Why

**Hole 1 -- the plan gate can pass when no plan was ever approved.**
Issue #54. `plan_header.branch_plan_path` redirects a branch named
`features/<x>` away from the feature-plan namespace, but every reader
still builds the path as the plain f-string `.canon/plans/<branch>.md`.
Reading the tree rather than the issue turns up **eight** such sites,
not the five the issue lists: `plan_gate.py`, `check_scope.py`,
`session_start.py` and `_config.py` on the hooks side, and `_config.py`,
`plan.py`, `position.py` and `ship.py` on the `canon_mcp` side. Two
consequences are sharp enough to matter on their own. `plan_gate`'s
`_plan_exists` returns `True` for a `features/<x>` branch purely because
a feature plan of that slug exists, so edits proceed as if a per-branch
plan had been approved when none was -- Canon's own "no edit without a
plan" gate, defeated by a branch name. And `canon_ship` reports the plan
invariant satisfied from that same wrong file, on the one call that
decides whether a human should look at the branch at all. A gate that
passes for the wrong reason is worse than one that is absent; that is
Canon's own rule, applied to Canon.

**Hole 2 -- the git guard can hand back a command that will not parse.**
Issue #58. `_strip_attribution`'s `_TRAILER_LINE` runs `.*` to the end
of the line, so a `Co-Authored-By:` trailer written as the last line
inside a quoted `-m` message takes the closing quote with it. Canon
returns that text through `updatedInput` as the command to actually run,
so the developer gets a shell parse error from a hook whose whole
purpose was to make the commit clean. Claude Code's own heredoc commit
style hides this today; the ordinary single-argument `-m "...trailer"`
form does not.

**Hole 3 -- a Codex user cannot install the companion plugin at all.**
`plugins/canon-companion` is listed only in
`.claude-plugin/marketplace.json`, and carries only a
`.claude-plugin/plugin.json`. Nothing about its content is
Claude-specific: it is one `SKILL.md`, one references file and one
standalone checker script, with no hook, no MCP server, no bundled
subagent and no `${CLAUDE_PLUGIN_ROOT}` anywhere in it. Every reason
`plugins/claude` and `plugins/codex` had to fork is absent here, so the
plugin is a Claude-only artifact purely by omission.

**Hole 4 -- four skills are vendored twice and nothing checks the copies
agree.** `decide`, `review-change`, `ship` and `testing-craft` are
byte-identical between `plugins/claude/skills/` and
`plugins/codex/skills/`; `frame`, `plan` and `review` genuinely differ
and are hand-maintained. `sync-check` covers `src/canon_hooks` and
`src/canon_mcp` and stops there, so editing a shared skill on the Claude
side leaves the Codex copy stale with CI green -- precisely the class of
bug `sync-check` was written to catch, one directory over.

**Hole 5 -- nothing names the version.** Four plugin manifests and two
marketplace entries all say `0.0.1`, with nothing checking they agree.
There is no tag, no CHANGELOG, and no record of what a first adopter is
getting.

## Success

- A branch named `features/<x>` reads its plan from the same path the
  save side writes it to, established by a test that fails against
  today's `main` at every one of the eight sites.
- `_strip_attribution` never changes the quote parity of the command it
  rewrites, established by a test over the quoted, single-quoted and
  heredoc forms.
- `codex plugin add canon-companion@canon` installs the same directory
  `claude plugin install canon-companion@canon` installs, confirmed
  against the real `codex` CLI, not inferred from its documentation.
- `just sync-check` fails when a shared skill drifts between the two
  plugins, and `just ci` is green on each pull request.
- One `v0.1.0` tag, one CHANGELOG describing what actually landed, and
  six version strings that agree.

## Non-goals

- **No merge of `plugins/claude` and `plugins/codex`.** Three skills
  genuinely differ because Codex has no `ExitPlanMode` and cannot bundle
  a subagent, and neither harness can be told to read a different
  `SKILL.md` per platform. The two-directory fork stays.
- **No conditional instruction text.** Rewriting the three divergent
  skills to branch on the harness is the tempting way to share them; it
  adds hedged prose to instructions and would owe an eval run. Not here.
- **No change to `docs/plan.md`.** It is the specification. Where code
  should win over the document, that argument belongs in
  `docs/decisions/`.
- **No eval runs, and no new instruction text that would owe one.**
  Every step here is code or manifests, so this release is not gated on
  quota. The ten open eval-run issues stay tracked debt, per
  `docs/decisions/0003-eval-suite-is-not-a-ci-gate.md`.
- **No attempt to fix the Codex MCP connection intermittency.**
  `docs/codex-hook-surface.md` establishes it is upstream of anything
  this repository controls. Step `release-packaging` makes it visible at
  the point of install; it does not chase it.
- **No new stored state.** Every step is subject to Invariant II.

## Shape

The three startable steps were chosen so that no two touch the same
file -- the constraint that decides how much of this can run at once,
since these items collide on files far more than they collide on
reasoning:

| Step | Touches |
|---|---|
| `read-side-plan-path` | `plan_gate.py`, `check_scope.py`, `session_start.py`, `_config.py`, and the four `canon_mcp` readers |
| `git-guard-trailer` | `git_guard.py` |
| `release-packaging` | both marketplace manifests, `Justfile`, `README.md`, `plugins/canon-companion/`, `plugins/codex/plugin.json` |
| `release-0-1-0` | six version strings, `CHANGELOG.md` |

So the first three are cut from `main` in parallel rather than stacked.
`read-side-plan-path` is the long pole and should start first;
everything else fits inside its wall-clock. The fourth waits on all
three, because a CHANGELOG written before the work lands describes work
that might still change shape.

Two coordination facts the three lanes have to respect. Both
`read-side-plan-path` and `git-guard-trailer` end by running
`just sync-hooks`, regenerating files under `plugins/*/hooks/`; the
files each touches are disjoint, so there is no textual conflict, but
whoever merges second re-runs `sync-hooks` and `sync-check` rather than
trusting the merge. And no branch here may be named with a `features/`
prefix: until `read-side-plan-path` lands, such a branch is read out of
the wrong file by the very gates these branches run under.

## Decisions

**`canon_mcp` mirrors the redirect rule rather than importing it.**
The obvious fix -- have every reader call
`plan_header.branch_plan_relative` -- is only available to the four
hooks-side sites. `canon_mcp` deliberately does not import `canon_hooks`
(see `_git.py`'s module docstring: two delivery mechanisms that should
not share a dependency edge, the same call already made for CoDev's
ported skills). So the `canon_mcp` side gets its own documented mirror,
and the step ships a parity test that pins the two implementations to
the same answer for the same branch name. A mirror with no parity test
is how the two copies drift; a dependency edge is the thing the
architecture already refused. The test is what makes the mirror
honest.

**The companion ships as one directory with two manifests, not as a
`canon-companion-codex` twin.** Codex enforces that a plugin's own
`plugin.json` name equals its marketplace entry name, where Claude Code
tolerates a mismatch -- which is exactly why `plugins/claude` and
`plugins/codex` need separate entries named `claude` and `codex`. The
companion is already called `canon-companion` on both sides, so one
directory satisfies both rules. Confirmed: a copy of the companion
carrying both `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`
passes `claude plugin validate --strict`. The Codex half of that claim
is the one thing here not yet confirmed against a real CLI, and
`release-packaging` is not done until it is.

**The version bump is its own step, and it is last.** It touches six
files that three other lanes also touch, and its CHANGELOG has to
describe what actually shipped. Bumping early would mean rewriting it.

## Steps

- read-side-plan-path (after: none): make every reader of a branch plan
  use the same path the save side writes to, so a `features/<x>` branch
  cannot be gated against the wrong file
- git-guard-trailer (after: none): stop the attribution stripper from
  taking a closing quote with the trailer it removes
- release-packaging (after: none): ship the companion to Codex from one
  shared directory, close the skills drift gap, and complete both
  marketplace manifests
- release-0-1-0 (after: read-side-plan-path, git-guard-trailer,
  release-packaging): one agreed version across six manifests, a
  CHANGELOG, and the `v0.1.0` tag
