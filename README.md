<p align="center">
  <img src="assets/canon-banner.png" alt="Canon" width="100%">
</p>

# Canon

A Claude Code plugin that keeps agentic development on track without a
stored state machine.

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

In place of that, Canon rebuilds on four Claude Code primitives:

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

Requirements:

- Claude Code, with plugins enabled.
- [`uv`](https://github.com/astral-sh/uv) on `PATH` -- `canon-mcp` runs
  through `uvx`, resolved on first use, nothing to build or install
  separately.
- [`gh`](https://cli.github.com), authenticated -- the `ship` skill opens
  pull requests with it.
- A git repository with a configured remote; Canon derives the protected
  branch from the remote's default rather than assuming `main`.

Add the marketplace and install the plugin from inside a Claude Code
session:

```
/plugin marketplace add urban233/Canon
/plugin install claude@canon
```

(or the non-interactive equivalent, `claude plugin marketplace add
urban233/Canon` and `claude plugin install claude@canon`.) The marketplace
is named `canon`; `claude` is this Claude Code implementation of it.

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
