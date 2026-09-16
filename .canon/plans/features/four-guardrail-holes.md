---
status: approved
steps:
---

# Four guardrail holes

Four places where a rule Canon states has no mechanism behind it, or
where a mechanism misfires, closed in four branch-sized steps. Found by
reading the shipped implementation against `docs/plan.md` §07 and §12.
The plan document is unchanged by this work and remains the
specification.

## Why

**Hole 1 -- the only gate the whole design rests on is unguarded.** §12
says Canon "never merges or closes a pull request", and the README
repeats it. `git_guard.py` matches `git ...` patterns only, so
`gh pr merge`, `gh pr close` and `gh pr review --approve` pass straight
through. Every other "never" in §12 got a deterministic pattern; the
most consequential one is prose in `ship/SKILL.md` that the model has to
remember. §07 is explicit that nothing in the spine may depend on the
model remembering an instruction.

**Hole 2 -- the verification command is never validated, and a broken
one is indistinguishable from a red suite.** `stop.py` runs
`shlex.split(command)` with no shell, so the most natural answer to the
first-run question -- `ruff check . && pytest` -- splits into
`['ruff', 'check', '.', '&&', 'pytest']` and fails forever. Worse, a
command that cannot be executed at all is handed back through the same
`block` path as a genuine test failure, so the agent is told to fix code
when the fault is configuration; after three refusals the gate gives up
and Canon is quietly toothless. "Wrong-but-plausible is worse than
absent" is the rule this violates, in Canon's own bootstrap.

**Hole 3 -- CI does not run the guard against vendoring drift.** The
`Justfile`'s `ci` recipe is `build test lint fmt-check typecheck
lock-check sync-check validate-plugin`, but `.github/workflows/ci.yml`
enumerates the steps by hand and omits `sync-check`. The drift guard
written for the bug fixed in 033815f is not enforced anywhere a pull
request can see it, and the hand-copied list is itself a drift surface.

**Hole 4 -- a branch named `features/x` silently overwrites the feature
plan `x`.** `save_plan.py` routes on a non-empty `## Steps`; otherwise
`branch_plan_path` produces `.canon/plans/features/x.md` for a branch
named `features/x` -- the feature-plan namespace. It is a silent
overwrite of the one artifact Canon does persist, in a system whose
pitch is that nothing can drift.

## Success

- Each hole has a closing commit with a test that fails without it.
- `just ci` is green on each pull request, established by GitHub Actions
  rather than by four concurrent local Bazel builds.
- The two steps that add instruction text ship their eval case files and
  a tracking issue for the run, never an unrun eval blocking the merge.

## Non-goals

- **No change to `docs/plan.md`.** It is the specification. Where code
  should win over the document, that argument goes in a decision record
  under `docs/decisions/`, not an edit to the spec.
- **Not the planning altitude.** Nothing here touches `frame`, feature
  plans as a concept, `_steps.py`, or `canon_position`'s feature
  reporting -- deliberately deferred.
- **No new stored state.** Every step is subject to Invariant II.
- **No shell execution of the verify command.** Step
  `verify-validation` refuses a compound command and names the fix; it
  does not gain a `shell=True` path.
- **No eval runs.** Case files ship with their step; the runs are
  deferred to issues, per
  `docs/decisions/0003-eval-suite-is-not-a-ci-gate.md`.

## Shape

The four are genuinely independent: no two touch the same file.

| Step | Touches |
|---|---|
| `gh-pr-guard` | `src/canon_hooks/git_guard.py` |
| `verify-validation` | `src/canon_hooks/_config.py`, `stop.py`, and the `canon_mcp` mirrors |
| `ci-sync-check` | `.github/workflows/ci.yml` |
| `plan-namespace` | `src/canon_hooks/plan_header.py`, both save hooks |

So they ship as four branches cut from `main` in parallel, not as a
stack -- unlike `phase-0-2-gap-closure.md`, whose ten steps shared a
header-derivation spine. `ci-sync-check` is the one worth merging first,
because it guards the vendoring the other three rely on, but that is a
merge-order preference and not a dependency: none of the four waits on
another to be startable, and `## Steps` below says so honestly.

## Decisions

**A compound verify command is refused, not shelled.** `ruff check . &&
pytest` could be made to work with `shell=True`. It is not, for two
reasons: Canon would then execute a config string through a shell, and a
partial failure inside a chain is ambiguous evidence -- which half was
red is exactly what the `Stop` gate has to report precisely. Refusing at
write time, and naming the fix (wrap it in a recipe and configure that),
keeps the evidence unambiguous and adds no execution surface. Canon does
not write the wrapper recipe itself: editing a repository's build
configuration is not Canon's, the same line it holds on `nbstripout` and
branch protection.

## Steps

- ci-sync-check (after: none): run the full `just ci` list in GitHub
  Actions, so the vendoring drift guard is enforced on every pull request
- gh-pr-guard (after: none): deny `gh pr merge`, `gh pr close` and
  `gh pr review --approve` in the `PreToolUse` git guard
- verify-validation (after: none): refuse a compound verify command when
  it is written, and report a command that cannot be executed as
  configuration rather than as a red suite
- plan-namespace (after: none): stop a branch named `features/<x>` from
  writing over the feature plan `<x>`
