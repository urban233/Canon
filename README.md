<p align="center">
  <img src="assets/canon-banner.png" alt="Canon" width="100%">
</p>

# Canon

[![CI](https://github.com/urban233/Canon/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/urban233/Canon/actions/workflows/ci.yml)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-D97757)](plugins/claude)
[![Codex Plugin](https://img.shields.io/badge/Codex-plugin-412991)](plugins/codex/README.md)

An agentic-development plugin, for Claude Code and Codex, that keeps work on
track without a stored state machine.

## Why "Canon"

**Canon** comes from the Ancient Greek **κανών** (*kanōn*): a builder's
straightedge, the rod against which a mason checked a wall for drift. Epicurus
later took the same word for his epistemology, *Kanonikē* -- the *kanōn* as
the objective criterion of truth, the standard that separates verified
reality from conjecture and hallucination.

That is the exact job this project does for agentic software engineering:

- **The straightedge.** An unyielding baseline that enforces architectural
  invariants and catches codebase drift as it happens, not at review time.
- **The criterion of truth.** Verification grounded in the repository's own
  runtime, filtering speculative claims and false positives out before a
  diff ever reaches a human.
- **The standard.** Review feedback that compounds into recorded project
  norms instead of being re-litigated every time it comes up again.

The mark is the same idea drawn once: a lyre strung in the shape of a **C**,
a straightedge a god hands down rather than an instrument anyone plays.

Canon is the successor to [CoDev](https://github.com/urban233/CoDev), built
on the finding that CoDev's own recorded history shows: **the state machine
CoDev used to track its own workflow was the largest source of the drift it
was built to catch.** Across CoDev's own task history, 47 of 73 rounds needed
a hand-written reopen, and 37 of 50 escalations were the machine failing on
its own bookkeeping commits. Canon has no equivalent to reopen.

In place of that, Canon rebuilds on four primitives every supported agent
platform provides -- described below as Claude Code provides them; see
[`plugins/codex/`](plugins/codex) for how the same four map onto Codex:

- **A `Stop` hook** that runs the repository's own verification command and
  refuses to let a turn end red -- so a claim like "tests pass" is a fact
  the harness checked, not something taken on the agent's word.
- **Plan mode, persisted.** Claude Code's plan mode already reads the
  repository and drafts a plan; Canon's only addition is saving the approved
  plan into the repository instead of letting it evaporate after 30 days.
- **A reviewer subagent** that reads a diff in a fresh context, so review
  never depends on the writer's own reasoning.
- **One small MCP server** (`canon-mcp`) that answers "where does this stand"
  by reading git, GitHub, and the plan file directly -- nothing is stored,
  so nothing can drift.

## What Canon brings

- **No compaction amnesia.** A plan approved in plan mode is written into the
  repository the moment it's approved, so it survives context compaction and
  session restarts instead of evaporating with the conversation that produced
  it.
- **No unverified "done."** A turn cannot end on the claim that tests pass
  unless the repository's own verification command actually ran and came
  back green at that exact commit.
- **No self-graded review.** Every change gets a verdict from a reviewer
  subagent that only ever sees the diff, the plan, and the evidence -- never
  the conversation that produced them, so review can't inherit the writer's
  own blind spots.
- **No accidental branch damage.** Editing on the default branch, or
  branching again from a branch you already made on purpose, is caught
  before the first edit, not discovered at commit time.
- **No new surface to babysit.** All of the above rides on primitives Claude
  Code already has -- plan mode, hooks, subagents, MCP tools. There's no
  dashboard, no separate CLI, and no task database that can fall out of sync
  with the repository it's supposed to describe.

## Install

Common requirements, either platform:

- [`uv`](https://github.com/astral-sh/uv) on `PATH` -- `canon-mcp` runs
  through `uvx`, resolved on first use, nothing to build or install
  separately.
- [`gh`](https://cli.github.com), authenticated -- the `ship` skill opens
  pull requests with it.
- A git repository with a configured remote; Canon derives the protected
  branch from the remote's default rather than assuming `main`.

### Claude Code

Requires Claude Code, with plugins enabled. The marketplace is named
`canon`; `claude` is this Claude Code implementation of it.

**Globally, for every project** (the usual choice for your own use) --
add the marketplace and install the plugin from inside a session:

```
/plugin marketplace add urban233/Canon
/plugin install claude@canon
```

(or the non-interactive equivalent: `claude plugin marketplace add
urban233/Canon` and `claude plugin install claude@canon`.) This is a
per-user install -- it becomes available in every project you trust,
recorded in your own `~/.claude` config, not this repository.

**Scoped to one project** (so a team gets it automatically without each
person installing it individually) -- run both commands with
`--scope project` from inside that project's checkout:

```sh
claude plugin marketplace add urban233/Canon --scope project
claude plugin install claude@canon --scope project
```

This writes the marketplace and the enabled-plugin entry into
`.claude/settings.json` at that project's root instead of your personal
config. Commit that file, and anyone who clones the project and trusts
the folder gets Canon enabled automatically -- nothing to run themselves.

**To remove it:** `claude plugin uninstall claude@canon` (add `--scope
project` to remove the project-scoped install instead of the global one),
then `claude plugin marketplace remove canon` with the same `--scope` if
you added the marketplace at project scope. For a project-scoped
install, this leaves an empty `.claude/settings.json` behind; delete it
(or just the `canon`/`claude@canon` entries, if the file has other
content) and commit that.

### Codex

Requires the [Codex CLI](https://developers.openai.com/codex), logged in.

**Globally, for every trusted project:**

```sh
codex plugin marketplace add urban233/Canon
codex plugin add codex@canon
```

This is the only install scope Codex's plugin manager has -- unlike
Claude Code, there is no `--scope project` flag, and `codex plugin add`
always writes into your own global `~/.codex/config.toml`, regardless of
whether the marketplace source was this GitHub repo or a local checkout.
Installing it globally doesn't mean its hooks start running everywhere
immediately: Codex reviews and trusts each hook definition individually
(by hash) before it will execute at all, separately from installing the
plugin -- see `plugins/codex/README.md`'s notes on hook trust vs. project
trust below.

**Scoped to exactly one project:** since there's no install-scope flag to
use instead, this means bypassing `codex plugin add` and copying the
pieces into that project's own `.codex/` directory by hand -- Canon's
`hooks/`, `skills/`, the two files under `agents/`, and
[`vendor/canon_mcp/`](plugins/codex/vendor/canon_mcp) all from
[`plugins/codex/`](plugins/codex), plus a `[mcp_servers.canon]` entry in
that project's own `.codex/config.toml` pointing `command`/`args` at the
copied-in `vendor/canon_mcp`. More manual than the global install, but it
never touches your global Codex config at all.

**To remove the global install:** `codex plugin remove codex@canon`, then
`codex plugin marketplace remove canon`. For a manual per-project install,
just delete the copied files from that project's `.codex/` directory.

Full install steps, hook/project trust, and what's genuinely different
about this port from the Claude plugin are in
[`plugins/codex/README.md`](plugins/codex/README.md).

## Use

There's nothing to configure up front. The first time a turn in a repository
would otherwise end unverified, Canon asks one question -- what command
should pass before a turn ends here -- proposing a default when it can infer
one. Answer it once and Canon writes `.canon/config.json` itself; every
later turn in that repository is checked against it silently. (You can also
create that file yourself beforehand, with a `verify` command, to skip the
question entirely.)

From there, work the way Claude Code already works: enter plan mode as
usual, and once a plan is approved, ask to ship when the work is done.
Canon's hooks, the reviewer subagent, and `canon-mcp` do the rest --
persisting the plan, gating the `Stop` on real evidence, dispatching an
independent review, and opening the pull request once `canon_ship` reports
the change is actually ready. Canon never merges, approves, or opens a
pull request on `main` itself -- that's always a human's call.

The full design -- evidence, invariants, architecture, every settled
question -- is written up at [`docs/plan.md`](docs/plan.md).

## Development

`just` is the build entry point (`just --list`); Bazel owns build, test,
lint and typecheck. Dev tooling (ruff, pyrefly) is pinned in
[`requirements.in`](requirements.in) and resolved hermetically as real
Bazel targets — no `uvx` in that path. `uvx` is reserved for `canon-mcp`'s
own runtime, resolved from source on first use rather than built by Bazel
(see `docs/plan.md` §05). See the [`Justfile`](Justfile). [GitHub
Actions](.github/workflows/ci.yml) runs the same checks on every pull
request and on `main`.

## License

BSD-3-Clause. See [`LICENSE`](LICENSE).
