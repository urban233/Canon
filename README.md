# Canon

A Claude Code plugin that keeps agentic development on track without a
stored state machine.

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

## Status

Phase 0 is done: the three hooks, first-run setup, the `canon-mcp`
server (`canon_position`, `canon_plan`), and the `plan` skill are all in
place. Phase 1 (the reviewer subagent) is next.

## The plan

Canon is built to a single design document, not discovered by using it. The
full design -- evidence, invariants, architecture, every settled question --
is at:

https://claude.ai/code/artifact/1453894c-9e0b-40fe-b661-d5f0e53eca5f

A markdown rendering lives at [`docs/plan.md`](docs/plan.md).

## Development

`just` is the build entry point (`just --list`); Bazel owns build, test,
lint and typecheck. Dev tooling (ruff, pyrefly) is pinned in
[`requirements.in`](requirements.in) and resolved hermetically as real
Bazel targets — no `uvx` in that path. `uvx` is reserved for the MCP
server's own runtime dependency once it exists (see `docs/plan.md` §05).
See the [`Justfile`](Justfile). [GitHub Actions](.github/workflows/ci.yml)
runs the same checks on every pull request and on `main`.

## License

BSD-3-Clause. See [`LICENSE`](LICENSE).
