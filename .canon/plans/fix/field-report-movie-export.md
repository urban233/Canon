---
status: approved
base: "def4b3d95"
stacked_on:
scope: "[src/canon_hooks/**, src/canon_mcp/**, plugins/claude/hooks/**, plugins/codex/hooks/**, plugins/antigravity/hooks/**, plugins/canon-relay/hooks/**, plugins/claude/vendor/**, plugins/codex/vendor/**, plugins/antigravity/vendor/**, plugins/claude/skills/**, plugins/codex/skills/**, plugins/antigravity/skills/**, plugins/claude/evals/**, tests/**, README.md, CHANGELOG.md, docs/decisions/0010-ship-evidence-is-verified-not-stored.md, docs/field-reports/**, .canon/plans/**]"
done: "Stacked branches measure from their parent, verdicts are per branch, and canon_ship verifies ship evidence by tree"
verify:
parent:
---

# Close the gaps the movie-export field report found

## Context

An agent used Canon 0.1.0 on a stacked feature in `open-protein-platform`
(step `movie-export`, cut from `movie-effects`). Its account was checked
claim by claim in
`docs/field-reports/2026-09-28-open-protein-platform-movie-export.md`,
committed on this branch together with ADR 0010. The plan-save hook is
already fixed in 0.2.1. What is still broken, verified in Canon's code:

1. **Verdicts are not scoped to a branch.** `last_decision` returns the
   newest record for a reviewer across the whole log, so a new branch
   inherits its parent's verdicts. The review skill's claim of "the last
   verdict on this branch" is false.
2. **Stacking is permitted by the spec but not modelled.** `base`, the
   SessionStart diff, `canon_review`'s changed paths and
   `canon_position` all measure from the merge-base with the default
   branch, so every step of a stack reports the whole stack.
3. **Ship evidence reaches Canon nowhere.** The real evidence (a slow,
   display-bound run) was carried in prose and matched to HEAD by
   timestamp. ADR 0010 decides how Canon verifies it without storing it.
4. **Every commit forces a full re-review.** A docs-only fix to a READY
   verdict's notes costs a full round, about 350k tokens and 15–20
   minutes.
5. **Nothing counts review rounds**, so the two-round stop is lost at
   compaction, even though the log holds the history.
6. **`.canon/hooks/decisions.jsonl` pollutes adopting repositories.**
   Canon assumes it is gitignored, but nothing tells a repository to
   ignore it. The docstrings calling it "never read back to make a
   decision" or "display only" are also wrong: `canon_ship` gates on it.
7. **Reviewer models can't be configured.** Both agents hard-code
   `model: opus`.
8. **The ship skill demands a `## Approach` section** that the plan skill
   never asks for.

The result ships as **0.3.0**, through a separate `chore/release-0-3-0`
PR. This PR carries only `[Unreleased]` CHANGELOG entries.

## Scope

- src/canon_hooks/**
- src/canon_mcp/**
- plugins/claude/hooks/**
- plugins/codex/hooks/**
- plugins/antigravity/hooks/**
- plugins/canon-relay/hooks/**
- plugins/claude/vendor/**
- plugins/codex/vendor/**
- plugins/antigravity/vendor/**
- plugins/claude/skills/**
- plugins/codex/skills/**
- plugins/antigravity/skills/**
- plugins/claude/evals/**
- tests/**
- README.md
- CHANGELOG.md
- docs/decisions/0010-ship-evidence-is-verified-not-stored.md
- docs/field-reports/**
- .canon/plans/**

## Done

Stacked branches measure from their parent, verdicts are per branch, and canon_ship verifies ship evidence by tree.

## Non-goals

- **No Canon-owned store of any kind**, per ADR 0010. Canon only reads
  what the repository writes.
- **No mutation-evidence convention** (the agent's suggestion 8). ADR
  0010 defers it to its own argument.
- **Nothing that edits a repository's `.gitignore` or untracks the log.**
  Canon reports and does not fix (§12's stance on branches applies).
- **No version bump or release in this PR.** That is
  `chore/release-0-3-0`.
- **No edit to `docs/plan.md`.** The spec isn't edited to match code;
  ADR 0010 is where a reader of §08/§15 lands.
- **No per-call reviewer models on Codex or Antigravity.** Their dispatch
  has no confirmed per-call override. Their review skills get the other
  text changes, for parity.
- **No GitHub lookups in hooks.** Stacked-parent resolution stays local
  to git and the plan file, so hooks gain no network call.
- **No handling for a parent step merged or retargeted after the child
  was cut**, beyond what the fallback rules below give. This goes under
  Risks.
- **No version check on installed plugins**, even though the field
  session ran 0.1.0. The README's update section (`def4b3d`) is the
  answer for now.

## Approach

Hooks code is edited only in `src/canon_hooks/` and vendored with
`just sync-hooks`; MCP code only in `src/canon_mcp/`, vendored with
`just sync-mcp`; shared skills (`ship`, `review-change`) are edited in the
Claude plugin and copied with `just sync-skills`. The divergent skills
(`review`, `plan`) are hand-edited on each platform. One commit per
numbered item below, tests in the same commit.

### 1. Scope verdicts to the branch

- `_common.log_decision` (`src/canon_hooks/_common.py:528`) adds
  `branch: current_branch(root)` to every record. That covers
  `capture_review.py` and `stop.py` with no change at their call sites.
- `last_decision(root, hook, branch=None)`, in both `_common.py:562` and
  `src/canon_mcp/canon_mcp/_decisions.py:22` (deliberately duplicated),
  skips records whose `branch` is set and differs. Legacy records
  without `branch` still match, for backward compatibility.
- Add `decisions_for(root, hook, branch)`, which returns all matching
  records, oldest first.
- `review.py` passes `current_branch`. Correct the docstrings
  (`_common.py:26-28`, `_config.py:6`, `_decisions.py:1-10`, and
  `review.py`'s header) to say `canon_ship` gates on these verdicts.

### 2. Model stacked branches

- Add `stacked_on(root, branch) -> str | None` to `_common.py` and,
  duplicated, to `canon_mcp/_git.py`. It tries these in order:
  1. the saved plan header's `stacked_on:`, human-editable;
  2. the branch reflog's `branch: Created from <X>`, when X isn't `HEAD`;
  3. the earliest HEAD-reflog entry `checkout: moving from <X> to <branch>`.

  X is accepted only if it is an existing local branch, other than the
  branch itself and other than the default branch. It must also be a
  real parent: `merge-base(HEAD, X)` differs from
  `merge-base(HEAD, default)`. Otherwise the answer is None.
- Add `base_ref(root, branch)`, which returns `stacked_on(...) or
  default_branch(root)`. The existing `merge_base(root, ref)` then gives
  `base`.
- Use `base_ref` in `plan_header.derive_branch_header` (`:342-343`),
  which also writes a derived `stacked_on:` line; in `session_start.py`
  (`:471-476`, with labels "Diff vs `<ref>`" and "Decisions since
  `<ref>`"); in `review.py:194`; and in `position.py:184-185`, which
  also reports `stacked_on`.
- `parent:` keeps its current meaning: the feature plan.
- **Found while saving this plan:** `merge_base` measures from the
  *local* default branch. When local `main` is behind `origin/main`, the
  base is stale and every diff grows. This plan's first header came out
  as `8df2b05c2` (#82) instead of `def4b3d95`. When `origin/<default>`
  exists, use `git merge-base HEAD <default> origin/<default>`, the
  latest fork point from either ref. Fix it in both `_common.py` and
  `_git.py`.

### 3. Verify ship evidence (ADR 0010)

- In `canon_mcp/_config.py`, add `ship_evidence_config(config)`. It
  accepts `{"command": str, "result": str}` and returns None when the
  key is absent or malformed. A malformed key is reported, never raised.
- Add `head_tree(root)` to `_git.py`, using `git rev-parse HEAD^{tree}`.
- In `evidence.py`, add `_ship_evidence(root, config)`. Its `status` is
  one of `passed | missing | malformed | stale | dirty | failed`, and it
  carries `command`, `result`, the recorded `tree` and `head_tree`. It is
  attached to every return of `build_evidence` when declared. Refactor
  so the key is attached once, not in each of the seven returns.
- In `ship.py`, when the key is declared and the status isn't `passed`,
  add one entry to `missing`: "ship evidence is `<status>`: run
  `<command>`".

### 4. Cheaper follow-up review (skill text)

- Add to the `review` skill: when a reviewer's own last verdict is
  READY FOR HUMAN APPROVAL and its `head` is an ancestor of HEAD, ask it
  for a **delta-only confirmation** of `<head>..HEAD`. It still returns a
  fresh verdict at HEAD, so `canon_ship`'s freshness rule is unchanged.
- The existing "in addition to the full range, never instead" rule
  stays for repair after CHANGES REQUIRED, which is where its regression
  argument applies.

### 5. Count review rounds

- `build_review` adds `rounds: {name: n}`, where n is the number of
  CHANGES REQUIRED records for that reviewer on this branch, from
  `decisions_for`.
- The `review` skill's "Nothing counts the rounds for you" paragraph is
  rewritten: the count comes from `canon_review`'s `rounds`, which is
  derived from the log and survives compaction. Stop at 2.

### 6. Report an untracked-log hazard

- `session_start.py` adds one sentence when
  `.canon/hooks/decisions.jsonl` is tracked (`git ls-files
  --error-unmatch`) or not ignored (`git check-ignore -q`, exit 1). The
  sentence names the exact fix: add `.canon/hooks/` to `.gitignore` and
  run `git rm --cached .canon/hooks/decisions.jsonl`. It fails open, so
  any git error means silence.
- The README's install section gains the `.gitignore` line.

### 7. Configure reviewer models

- In `canon_mcp/_config.py`, add `reviewer_models(config)`, reading
  `{"reviewers": {"<name>": {"model": "<alias or id>"}}}`.
- `build_review` adds `models`, only for configured names.
- The Claude `review` skill tells the agent to dispatch with the model
  `canon_review` names, when one is named. Unset means the agent's
  frontmatter default (opus).

### 8. Align ship with plan

- The shared `ship` skill reproduces the plan's `## Non-goals` and its
  approach section (`## Approach`, or whatever the plan uses, such as
  `## Design`) verbatim.
- It states the command `canon_evidence` reports as green, and the
  ship-evidence result when one is declared.

### Evals (owed, not run)

Instruction text changes in items 4, 5, 7 and 8, so each gets an eval
case written in this PR, validated by `just eval-check` (which is free):

- new `reviewer-confirms-only-the-delta-after-ready`;
- new `review-counts-rounds-from-canon-review`;
- new `reviewer-dispatch-uses-the-configured-model`;
- new `ship-reproduces-a-design-section`;
- extend `ship-not-ready` with a stale ship-evidence arm.

Then **one GitHub issue** names each case, what it must show, and what to
do if it fails. No `claude plugin eval` run without explicit approval.

### Docs

- README config reference: `ship_evidence`, `reviewers`, `stacked_on:`
  and how stacking is detected, and the `.gitignore` step.
- CHANGELOG `[Unreleased]`: Added, Changed and Fixed, one long line per
  entry.

## Verification

- `just ci` (build, the full `bazel test`, lint, fmt, typecheck,
  sync-check, eval-check, validate-plugin).
- New tests per item:
  - `test_canon_mcp_review.py` (branch scoping, legacy records, rounds,
    models, stacked base);
  - `test_canon_mcp_ship.py` and `test_canon_mcp_evidence.py` (every
    ship-evidence status, the tree match, a key without the file);
  - `test_claude_hooks_session_start.py` (diff vs parent, the
    untracked-log notice, silence on a git error);
  - `test_claude_hooks_save_plan.py` (the `stacked_on:` header and
    `base` at the parent's fork point);
  - the capture-review and `_common` tests (the `branch` field);
  - resolver tests for `stacked_on` (branch reflog, HEAD reflog, header
    override, the default branch rejected, a non-parent rejected).
- End-to-end on a scratch repository shaped like the field case
  (`main → a → b`, with `b` cut by `git switch -c b` from `a`):
  - approve a plan through `save_plan.py` and check that the header has
    `stacked_on: a` and `base` = `merge-base(b, a)`;
  - check that SessionStart reports "Diff vs `a`";
  - log a verdict on `a`, then check that `canon_review` on `b` shows
    none;
  - write a ship-evidence file with the wrong tree and check that
    `canon_ship` names `stale`.
- A read-only check against the real field worktree
  (`open-protein-platform.worktrees/app-kit-probe`): call
  `build_review`, `build_position` and `stacked_on` with root pointed
  there, with no writes. Record whether `movie-export` resolves to
  `movie-effects`.

## Risks / Stop if

- **Reflog heuristics are local.** A branch fetched on another machine
  has no "Created from", so it falls back to the default branch, which
  is today's behaviour. `stacked_on:` in the header fixes it by hand.
  Stop and ask if the real field worktree resolves to anything other
  than `movie-effects`.
- **A parent merged by squash** keeps `stacked_on:` pointing at a branch
  that may be deleted. A missing branch falls back to the default.
- **Legacy log records match every branch** until a new record is
  written. The staleness flag still marks them.
- Adding `branch` to every record grows the log slightly. That's
  acceptable.
