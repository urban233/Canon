# Field report: Canon on `open-protein-platform`, step `movie-export`

An agent that had just finished one step of a stacked feature was
interviewed about using Canon. Each of its claims is checked here against
the project's repository, its Claude Code transcripts, and Canon's own
code on `main` (as of 0.2.1). Its experience is kept separate from what
could be measured, because both matter: a verified defect says what to
fix, and a perceived cost says where the agent will start working around
Canon.

## Context

- **Project:** `open-protein-platform`, worktree `app-kit-probe`, branch
  `movie-export`. That is step 8 of the feature plan
  `features/movie-timeline-probe.md`, cut from `movie-effects` (PR #84),
  which was itself stacked on earlier `movie-*` steps.
- **When:** 2026-09-27 and 2026-09-28, in one Claude Code session that
  was compacted twice.
- **Canon version loaded:** **0.1.0**, from
  `~/.claude/plugins/cache/canon/claude/0.1.0/`, although 0.2.0 had been
  released on 2026-09-20. Both versions carry the plan-save bug fixed in
  0.2.1: 0.1.0's `save_plan.py:96` has the same `isinstance(tool_response,
  str)` check.
- **Reviewers:** four rounds, each with `reviewer` and `risk-reviewer`,
  at commits `3d23ac4e4`, `2e6fb6d25`, `8025855f4` and `49ab00398`.

## Legend

| Mark | Meaning |
|---|---|
| **Verified** | Confirmed by code, git, the decisions log or a transcript. |
| **Partly** | The substance holds, but a detail is wrong or overstated. |
| **Contradicted** | The evidence says otherwise. |
| **Stated by the agent** | A judgement or experience. It cannot be measured, but it is still data. |

## Measurable claims

### What Canon did well

| Claim | Status | Evidence |
|---|---|---|
| Round 1 raised one blocking finding: the plan asked for a record of what stock PyMOL shows on a jump, and it was missing. | Verified | `decisions.jsonl`: `reviewer` returned CHANGES REQUIRED at `3d23ac4e4` (00:51:49), "one missing record". Fixed in `2e6fb6d25`. |
| "21 of 60 frames differ after one jump from load." | Verified | The figure appears verbatim in a reviewer subagent's transcript, as the agent's measurement. |
| Replay waited on a clock rather than PyMOL's latch. | Verified | The `2e6fb6d25` message says replay now waits for the shim's own latch. |
| The navigator's Slide actions came ahead of the export guard. | Verified | Fixed in `2e6fb6d25`: "the navigator's Slide actions wait for it too". |
| The Effect menu enabled its own items, bypassing the guard. | Verified | `8025855f4`: "The Effect menu enables its own items". |
| PyMOL's `save` expands `$NAME`, so `Price $USER.pse` was written as `Price rootm.pse`. | Verified | Reproduced verbatim in a reviewer transcript. Fixed in `8025855f4`. |
| The first `$` fix checked the raw argument, not the resolved path. | Verified | Fixed in `49ab00398`, "check replay's resolved path". |
| `load_session` did not refuse while thumbnails were queued. | Verified | Fixed in `49ab00398`. |
| Five bugs came from the agent's own mutation runs, about 40 mutants in all. | Verified | The transcript names all five. Mutation scripts and result files are in the session scratchpad (`export_mutants.py`, `rmut-results*.txt`, `xmut*/results.txt` and others). The count of 40 was not independently recounted. |

### Where Canon got in the way

| Claim | Status | Evidence |
|---|---|---|
| The plan-save hook fails, so the plan was written by hand. | Verified, now fixed | `ExitPlanMode` was approved at 22:40:59. The plan was then written with a Bash heredoc (not the Write tool) under a memory rule, `canon-plan-save-fallback.md`, which authorises exactly that. Root cause: `save_plan.py` expected a string `tool_response`, but Claude Code sends an object. Fixed in #90 and released as 0.2.1. |
| Every plan header's `base` is the stack root, `199825dd1`. | Verified | All 13 plans have `base: "199825dd1"`, the merge of #36 ("… integrate Canon"). That commit is the merge-base with `main` of every `movie-*` branch. Canon code: `plan_header.py:342-343` takes `merge_base(root, default_branch)`. |
| The SessionStart position diffs against `main`: 326 files and 113k lines. | Verified | `git diff --shortstat main...movie-export` gives 326 files, +113,736 / −441. Canon code: `session_start.py:471-472` and `:390`, "Diff vs `{default_branch}`". |
| On the new branch, `canon_review` first showed `movie-effects`' verdicts at `fd5fe9cf5`, marked stale. | Verified | The transcript's `canon_review` result at 2026-09-28T00:29:46Z returns both verdicts at `fd5fe9cf5` with `stale: true`. Canon code: `_decisions.last_decision` returns the newest record for a hook name across the whole log. Records carry no branch or plan field, so nothing can scope them. |
| The verify command is `ruff check .`, so "HEAD is green" rested on ruff alone. | Partly | The configured command is `bazel run //tools/bazel/devtools:ruff -- check .`, a Bazel wrapper around ruff, and every plan's `verify:` is blank. The substance holds: a local `canon_evidence` ran only ruff. For a pushed commit `canon_evidence` reads CI instead (`evidence.py:106`), so what it rests on depends on the project's CI. |
| `evidence.json` records no commit, and a reviewer matched it to HEAD by timestamp. | Verified | This is the project's own file, not Canon's. `run_evidence.py` writes it to a temporary directory, and `evidence_checks.collect()` writes no commit or tree field. Canon has no evidence store by design (`docs/plan.md` §08, "Why there is no evidence store"). |
| Every fix makes the verdicts stale and needs a full new round. | Verified | `review.py:132`: `stale = recorded_head != current_head`, so any commit makes a verdict stale, docs-only ones included. `ship.py:59-60` refuses on a stale verdict. There is no scoped confirmation path. |
| Four rounds. Rounds 2 and 3 were READY with notes, and fixing those notes forced the next round. | Verified | Round 1: reviewer CHANGES REQUIRED, risk-reviewer READY. Rounds 2, 3 and 4: both READY, each with non-blocking notes. |
| Two documentation nits were left open, to escape the loop. | Verified (fact), stated (motive) | Round 4's risk-reviewer: "Two non-blocking fixes, both documentation". There is no commit after `49ab00398`. The motive is the agent's own account. |
| Each round costs 15–20 minutes and about 350k subagent tokens. | Verified | Tokens for reviewer plus risk-reviewer: round 1 423k, round 2 353k, round 3 381k, round 4 349k. Wall clock per reviewer: 13–21 minutes. Round 1 was the heaviest because both reviewers ran on Opus (next row). |
| The two-round stop isn't tracked, and after a compaction the count lives only in the summary. | Verified | The session was compacted twice. `skills/review/SKILL.md:64-70` says so itself: "Nothing counts the rounds for you… after a compaction the count is gone". The history can be rebuilt from `decisions.jsonl`, as this report did. One nuance: the rule counts CHANGES REQUIRED verdicts, and there was only one, so the rule was never close to firing. |
| `.canon/hooks/decisions.jsonl` is always modified and had to be left out of commits by hand. | Verified | It is tracked: added in `5a7f1bb34`, the commit that set Canon up. It shows as `M` in the tree, and no `movie-*` commit touches it. Canon's code assumes the file is gitignored (`_common.py:26-28`), but only Canon's own `.gitignore` ignores `.canon/hooks/`. Nothing tells an adopting project to do the same. |
| Ship wants `## Approach` verbatim, but the plan skill never asks for one. | Verified | `skills/ship/SKILL.md:20-21` asks for it. `skills/plan/SKILL.md` names Scope, Done, Parent, Non-goals and Verification, never Approach. |
| No reviewer model is configured anywhere, so the user had to say Sonnet and Opus. | Partly | A model *is* set: both `agents/reviewer.md` and `agents/risk-reviewer.md` hard-code `model: opus`. What is missing is a way to configure it. The user's message is verbatim in the transcript: "use the Sonnet model for general Canon review and Opus only for the risk review". Round 1 ran without an override, so both reviewers used Opus; rounds 2–4 passed `sonnet` and `opus`. |

## Stated by the agent

These describe the agent's experience and are not measured. They are
recorded as given.

- **The review loop pays for itself.** Reviewers that never saw its
  reasoning improved the export step "in ways I wouldn't have reached
  alone". The verified findings above support this but can't prove the
  counterfactual.
- **The saved plan was what the reviewers checked against.** The one
  blocking finding came from reading the plan back.
- **`canon_review`'s staleness tracking made delta reviews "mechanical
  and correct"**, because the agent always knew which range to hand
  each reviewer.
- **`canon_ship` "stopped me opening the PR on my own word."**
- **Reviewers and mutation testing complemented each other.** Each found
  things the other could not.
- **Every step started with a workaround**, because of the broken
  plan-save hook.
- **The re-review cost creates "the wrong incentive"**: it pushes against
  fixing small things.
- **The real evidence never reached Canon.** The display-bound evidence
  run, the Swift and Python suites and the mutants were carried by hand
  in prompts and PR text.
- **Overall:** the review and ship gates improved the output. The
  friction came from how Canon models branches, evidence and the cost of
  re-review.

## Found while verifying, not raised by the agent

1. **The session ran 0.1.0, six days after 0.2.0 shipped.** Installs
   don't update themselves. The README has only covered updating since
   `def4b3d`.
2. **Canon's docstrings understate how the decisions log is used.**
   `_common.py:26-28` calls `decisions.jsonl` a diagnostic "never read
   back to make a decision", and `_decisions.py` says "display only".
   But `ship.py:55-68` gates readiness on the verdicts read from it.
3. **The review skill promises branch scoping that the code lacks.**
   `skills/review/SKILL.md:71-72` says `canon_review`'s `verdicts` "still
   tells you the last verdict on this branch". It is actually the last
   verdict anywhere in the repository, which is exactly how the
   `fd5fe9cf5` confusion arose.
4. **The spec allows stacking, but the implementation doesn't model it.**
   `docs/plan.md` (around line 1085) has Canon ask "stack on this branch,
   or branch from the default?". Once you stack, though, `base`, the
   SessionStart diff and `canon_review`'s changed paths (`review.py:194`)
   all measure from the default branch. The header's `parent:` names a
   feature plan, not a parent branch.

## The agent's suggestions, set against what was verified

In the agent's order.

| # | Suggestion | Problem behind it | Conflicts with the spec? |
|---|---|---|---|
| 1 | Stacked branches: parent branch in the header, `base` at the parent's head, verdicts per branch, diffs against the parent | Verified | No. It completes what the spec already permits. |
| 2 | Tiered, recorded evidence stamped with commit and tree | Verified (Canon never sees ship-level evidence) | **Yes.** `docs/plan.md` §08 rejects an evidence store. Changing that needs a decision record, not just an implementation. |
| 3 | A cheaper follow-up review for docs-only or notes-only deltas | Verified (any commit makes a verdict stale) | Needs care: it weakens "fresh verdict at HEAD". |
| 4 | Count review rounds from the verdict history | Verified | Partly. The skill deliberately keeps no counter, but deriving the count from the log stores nothing new. |
| 5 | Keep `decisions.jsonl` out of the working tree | Verified | No. It matches the invariant that Canon writes no repository state. |
| 6 | Reviewer models in config | Partly verified (hard-coded, not absent) | No. |
| 7 | Fix plan save, and align the plan and ship skills | Verified | Plan save is fixed in 0.2.1. The Approach mismatch is still open. |
| 8 | A convention for recording mutation evidence | Stated by the agent (need) | Same tension as #2. |
