---
status: approved
steps:
---

# Phase 0–2 gap closure

Nine deviations between `docs/plan.md` §06–§09/§12 and the code that
ships Phases 0–2, closed in ten branch-sized steps. Written after an
audit of the implementation against the plan; the plan document is
unchanged by this work and remains the specification.

## Why

Phases 0, 1 and 2 are shipped and coherent, but four behaviours the plan
names explicitly are absent, one mechanism is dead code, one guard denies
two harmless commands outright, and one gate can block forever in a
degraded payload. Phase 3 is ablation — *delete instructions until
something fails*. An eval written against `check_scope`'s glob half would
fail today for a reason that has nothing to do with the instruction text,
and the same is true of the plan-header `verify:` override. Closing these
first is what makes Phase 3's signal mean anything.

## Success

- Every numbered finding below has either a closing commit, a recorded
  decision saying why the plan's sentence no longer applies, or an
  explicit withdrawal saying it stays open (see step 9).
- `.canon/config.json` exists in this repo and Canon gates its own
  development — currently it does not, so none of this is dogfooded.
- `just ci` stays green at every step; each step is one branch and one
  pull request.

## Non-goals

- **No change to `docs/plan.md`.** It is the specification. Where the
  code should win over the document, that argument goes in a decision
  record under `docs/decisions/`, not an edit to the spec.
- **No `monitors/`.** §07 marks it optional and assigns it to no phase.
- **Not the `PostToolUse` formatter.** `check_scope.py` documents why it
  was deferred (stdlib-only hooks, no resolvable formatter binary); that
  reasoning still holds and this work does not revisit it.
- **No new stored state.** Every step below is subject to Invariant II.
  If a step looks like it wants a cache, it is wrong.
- **Not Phase 3.** No eval suite here; this is what Phase 3 runs against.

## Shape

Three kinds of work, deliberately ordered so the cheap and isolated
lands before the cross-cutting:

1. **Bug fixes** (steps 1–2) — self-contained, no shared surface.
2. **Invariants and the plan header** (steps 3–6) — the header
   derivation chain is the spine: `scope:`/`done:`/`parent:` derived at
   save time is what brings `check_scope`'s glob matcher, the `verify:`
   override and the `frame` → branch-plan link to life. Nothing
   downstream works until step 4 lands.
3. **New surface** (steps 7–9) and housekeeping (step 10).

Two shared helpers get introduced and everything else composes out of
them: `_config.canon_is_active()` (step 3) and
`_config.resolve_verify_command()` (step 5). Both are duplicated into
`canon_mcp/_config.py` under the existing copied-and-forked rule — hooks
and the server do not share a dependency edge.

## Stacking and merge order

The ten steps ship as a **stack**: each branch is cut from the one
before it and its pull request targets that branch, not `main`. Work on
step N+1 starts as soon as step N's pull request is open, so review is
never the thing holding the series up.

```
main
 ├── gap/1-git-guard-false-positives          PR → main
 │    └── gap/2-stop-hook-degraded-payload     PR → gap/1
 │         └── gap/3-inert-without-...          PR → gap/2
 │              └── gap/4-derive-plan-header-fields
 │                   └── gap/5-plan-verify-override
 │                        └── gap/6-ask-once-for-missing-sections
 │                             └── gap/7-feature-step-position
 │                                  └── gap/8-notebooks
 │                                       └── gap/10-docs-and-status
 └── (step 9 withdrawn -- see below)
```

**Why linear rather than several parallel branches off `main`.** Almost
every step touches a file another step touches — `git_guard.py` (1, 3),
`stop.py` (2, 5), `hooks/_config.py` (3, 5), `save_plan.py` (4, 5, 6),
`check_scope.py` (3, 4), `position.py` (7, 8), `session_start.py` (3, 8).
Parallel branches would resolve those as merge conflicts at the end
instead of as ordinary edits along the way. There is also a quieter
reason: three steps add a decision record, and the `decide` skill
allocates `NNNN` by listing `docs/decisions/` for the highest existing
prefix. In a stack each branch sees its predecessor's records and numbers
correctly; in parallel branches all three would claim `0001`.

**Step 9 is the exception** and branches off `main` directly — it touches
only a new test target, the `Justfile` and CI, and shares no file with
any other step. It can be reviewed and merged at any point.

### How to merge

Merge **bottom-up, one at a time, with a merge commit**:

```
gh pr merge <n> --merge
```

When a pull request merges, GitHub automatically retargets any open pull
request that was based on its head branch — so the moment step 1 lands on
`main`, step 2's pull request retargets itself to `main` and its diff
stays exactly its own changes. Nothing needs rebasing and nothing needs
reopening. Repeat up the stack.

Three things to hold to:

- **Never squash-merge or rebase-merge a branch in this stack.** Both
  rewrite commit SHAs, which means the next branch up still carries the
  originals: after retargeting, its pull request would show the previous
  step's changes again as its own diff, and every remaining branch would
  need rebasing to recover. This repository allows all three merge
  methods, so the wrong button is present in the UI — consider turning
  squash and rebase off for the duration of the series.
- **Merge in order.** Merging step 4 before step 2 pulls steps 2 and 3
  into it, because they are its ancestors.
- **Reviewing sees only the step.** Each pull request diffs against its
  own base, so step 5's page shows step 5's changes alone, not steps 1–5.

If review asks for a change to a step that is still open lower in the
stack, the fix is pushed to that branch and then merged *up* the stack
(step 3 into step 4, step 4 into step 5, and so on) so later branches
pick it up. With merge commits this is mechanical; it is the one piece of
upkeep a stack costs, and the reason the steps most likely to be
contested — the three carrying decision records — are placed as low in
the stack as their dependencies allow.

### Two frictions worth knowing about

Both are Canon gating its own development, and neither bites during this
series because `.canon/config.json` does not exist here until step 10:

- `plan_gate.py` gates `git checkout -b` when the current branch is not
  the default one — which is exactly what cutting the next branch in a
  stack does. Its message already anticipates this ("say explicitly
  whether to stack on 'X' or branch from 'main'"), so in `pair` or `solo`
  it is an answerable prompt rather than a wall.
- `git_guard.py` denies `git merge` outright, so the stack can never be
  merged locally. That is §12 working as intended: merge authority is a
  human's, exercised through `gh pr merge` or the GitHub UI, neither of
  which the guard touches.

### One thing to set up first

`main` has no branch protection and no required checks, so nothing
currently stops a red pull request from merging — and "CI green at every
step" is the property this whole series depends on. §12 calls for a solo
repository to be a protection rule requiring zero approvals rather than a
per-change waiver. Before merging step 1:

```
gh api -X PUT repos/urban233/Canon/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": { "strict": false, "contexts": ["ci"] },
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

`"strict": false` is deliberate and matters for this series. Strict mode
requires a branch to be up to date with its base before merging — which
in a stack is never true, because step N+1 does not contain the merge
commit that just put step N on `main`. Every merge would then demand an
"Update branch" click and a full CI re-run on each remaining branch.
Required checks still have to pass; only the up-to-date requirement is
dropped, and `ci` re-runs on every push regardless.

## Steps

### 1 · `git-guard-false-positives` — closes finding 2

Two patterns in `plugins/claude/hooks/git_guard.py` deny harmless
commands, as `deny` with no `ask` and no override:

| Command | Denied as | Pattern at fault |
|---|---|---|
| `git merge-base HEAD main` | a merge | `\bgit\s+merge\b` |
| `git push origin HEAD:refs/heads/x` | a remote branch deletion | `:\S` |

`merge-base` is read-only, and it is the exact command canon-mcp itself
runs in `src/canon_mcp/canon_mcp/_git.py`.

- Change `\bgit\s+merge\b` to `\bgit\s+merge(?![-\w])` so `merge-base`
  and `merge-file` fall out, and add a negative lookahead for
  `--abort`/`--quit`/`--continue` — aborting a merge is recovery, not
  the destructive operation §07 names.
- Change `:\S` to `\s:\S` so a colon-prefixed refspec (`git push origin
  :branch`, which deletes) still matches but `HEAD:refs/heads/x` does
  not.

Both replacements are verified against the cases below; `_NON_DELIMITER`
is the existing module constant:

```python
re.compile(rf"\bgit\s+merge(?![-\w])(?!{_NON_DELIMITER}--(abort|quit|continue)\b)")
re.compile(rf"\bgit\s+push\b{_NON_DELIMITER}(--delete\b|\s:\S)")
```

Denied: `git merge main`, `git merge --no-ff feat`, `git push origin
:oldbranch`, `git push --delete origin x`. Allowed: `git merge-base HEAD
main`, `git merge-file a b c`, `git merge --abort`, `git push origin
HEAD:refs/heads/feat`, `git push origin main`.

**Done when** `tests/test_claude_hooks_git_guard.py` has a regression
case for each of the nine commands above — two allowed, two denied — and
the existing deny cases still pass.

### 2 · `stop-hook-degraded-payload` — closes finding 5

`_common.state_dir()` returns `None` when the payload carries no
`scratchpad_dir`. `stop.py` then degrades badly in two places:

- `_read_refusal_count(None)` is always `0`, so `refusals` is always `1`,
  so the `> _MAX_CONSECUTIVE_REFUSALS` give-up branch is unreachable and
  a persistently-red repository blocks every turn end forever.
- `_has_been_prompted(None)` is always `False`, so the first-run question
  is asked on every `Stop`, not once.

There is also no `stop_hook_active` check — the harness's own loop guard.

- Read `stop_hook_active` from the payload and use it **only** as the
  fallback when `state_dir` is `None`: it substitutes for both the
  prompted-once marker and the give-up counter, so a hook with no
  scratchpad still terminates.
- Keep the counter as the primary mechanism where a scratchpad exists —
  `stop_hook_active` cannot count, and a one-shot backstop is a weaker
  guarantee than three attempts.

**Done when** `tests/test_claude_hooks_stop.py` covers a payload with no
`scratchpad_dir` for both paths: the first-run question asked once, and a
red verification that gives up rather than blocking indefinitely.

### 3 · `inert-without-verification-signal` — closes finding 1

§07 is explicit: *"If no command can be established, Canon **stays
inert** rather than running without it. Not the gate alone — the whole
plugin."* Today only `stop.py` checks `has_verification_signal`.
`plan_gate.py`, `check_scope.py` and `git_guard.py` never load the
config, so a repository with no `.canon/config.json` gets its first
`Edit` gated and `git merge` denied — the opposite of inert. This is also
a §15 settled question, which makes it the deviation with the most
weight behind it.

- Add `canon_is_active(config) -> bool` to `plugins/claude/hooks/_config.py`
  as a named predicate (it delegates to `has_verification_signal`, but
  the name is what the call sites should read).
- Make `plan_gate.py`, `check_scope.py` and `git_guard.py` load the
  config and return silently when it is false.

Two hooks deliberately stay live, and this is the part that needs
writing down rather than assuming:

- **`stop.py`** — it *is* the bootstrap. Its first-run block is the only
  mechanism that puts the question in front of the developer.
- **`session_start.py`** — pure `additionalContext`, never a gate. It is
  how a developer learns Canon is inert (`Verify: not configured yet`).
  Silencing it would make an inert Canon indistinguishable from a broken
  one.

`capture_review.py` goes inert with the gates: the verdict it captures
feeds `canon_ship`, which is a gate, so capturing while inert would
accumulate evidence for a check that must not run.

**Done when** each of the three gating hooks has a test asserting it is a
no-op with no config present, `session_start` has one asserting it still
injects, and `docs/decisions/0001-what-inert-means.md` records the
`stop`/`session_start` carve-out and why.

### 4 · `derive-plan-header-fields` — closes findings 3 and the dead half of 5

The spine of this work. `save_plan.py` writes `scope:`, `done:` and
`parent:` blank **unconditionally**, and nothing else ever fills them.
§06 says the hook derives "changed-paths intent" and its worked example
shows `scope:` and `done:` populated. Three things are broken by this:

- **`check_scope.py`'s glob half is dead code.** Its departure check only
  fires when `patterns` is non-empty, which never happens. The §07 row
  promises "the plan's allowed paths *and* its `## Non-goals`" and
  delivers only the second.
- **`parent:` is never set**, so `canon_plan`'s parent resolution and the
  whole `frame` → branch-plan link are inert unless hand-edited.
- **`plugins/claude/skills/plan/SKILL.md` tells the model a falsehood**:
  *"These become the saved plan's header fields."* Nothing parses them
  out of the body.

The mechanism §06 actually describes is that the `plan` skill *seeds the
headings while plan mode is drafting*, and the hook reads them back — so:

- In `save_plan.py`, read `## Scope`, `## Done` and `## Parent` out of
  the approved body with the existing `_common.plan_sections`, and write
  them into the header. Normalise `## Scope` to the bracketed glob list
  `check_scope._parse_scope_patterns` already reads; take `## Done`'s
  first line as a single-line scalar; validate `## Parent` resolves to a
  file under `.canon/plans/features/` before writing it.
- **Blank stays blank.** A section that is absent leaves its field empty
  — §06's "derived, not demanded, and never invented" is not relaxed by
  this step. Nothing is inferred from git: at approval time the branch
  has no changes to infer from.
- Update `plan/SKILL.md` to name those three headings exactly, so the
  model seeds them where the hook looks, and delete the claim that is
  currently false.

**Done when** `save_plan` tests cover all three fields present, absent,
and malformed; `check_scope` has a test where a populated `scope:`
produces a departure and a matching path does not; and `canon_plan`
resolves a parent written this way.

### 5 · `plan-verify-override` — closes finding 4

§07's table: *"`verify:` in a plan header | Overrides it for that
branch."* `save_plan.py` writes the field; `stop.py` and
`canon_mcp/evidence.py` read `.canon/config.json` only and never look at
the plan header.

- Add `resolve_verify_command(root, branch)` to
  `plugins/claude/hooks/_config.py`: the branch plan header's `verify:`
  when non-empty, else the config's. Use it in `stop.py`.
- Mirror it into `src/canon_mcp/canon_mcp/_config.py` and use it in
  `evidence.py`, so a local re-run and the `Stop` gate never disagree
  about which command counts.

**One thing must change with it, or the override is a trap.** Today
`save_plan.py` copies the config's `verify` into every header at approval
time. The moment the override is honoured, that copy *pins* the command
as of approval — a later edit to `.canon/config.json` would be silently
ignored on every existing branch. So `save_plan.py` must stop writing
`verify:` from config, and write it only when the plan body asked for a
different one (a `## Verification` section naming an explicit command).
Depends on step 4's body-reading machinery.

**Done when** a plan header naming a different command wins over the
config in both `stop.py` and `evidence.py`, a blank header falls back to
config, and a test asserts a config edit is visible to a branch whose
plan predates it.

### 6 · `ask-once-for-missing-sections` — closes finding 6

§06: *"At save time the hook checks only that the two required ones are
present and non-empty. Missing → it asks, once. It never rejects a
plan."* Today `save_plan.py` writes `notes: "Non-goals section is missing
or empty"` into the header and emits nothing — nobody sees it — while
`canon_mcp/ship.py` *does* block readiness on that note. The behaviour is
inverted from the spec: silent where it should ask, blocking where it
should not.

- Have `save_plan.py` emit `additionalContext` naming the missing
  section(s) once, at save time — which is the "asks, once" §06 means,
  and it costs nothing because `PostToolUse` already returns a payload.
- Keep `ship.py` blocking. §06's "never rejects a plan" governs the
  *plan*; shipping is a different gate with different authority, and a
  change with no `## Verification` section genuinely is not ready for a
  human. Record this in `docs/decisions/` rather than leaving the
  apparent contradiction for the next reader to rediscover.

**Done when** a plan missing either required section produces a visible
one-time message, the header note is unchanged, and the decision record
explains why ship still blocks.

### 7 · `feature-step-position` — closes finding 8

§06: *"`canon_position` reads the parent's list, checks which branches
exist and which PRs merged, and computes the answer."* `position.py`
never touches the parent or `## Steps`. `canon_plan` returns the parent
document, but nobody derives position *within* a feature — so Phase 2's
frame work landed as documents without the derivation behind them.

- New `src/canon_mcp/canon_mcp/_steps.py`: parse the parent plan's
  `## Steps` into an ordered list, and for each step resolve whether a
  branch exists, whether it merged, and its PR state — all from `git
  branch`/`git log` and the existing `_gh.py`, stored nowhere.
- **Matching steps to branches needs a convention, not a heuristic.**
  Have `frame/SKILL.md` require each step to lead with its branch slug
  (`- slug: description`), and match on that. Fuzzy-matching prose
  against branch names is exactly the kind of wrong-but-plausible §07
  warns about.
- `canon_position` gains a `feature` field (plan path, current step,
  total, completed) and `next_step` names the step when a parent exists.

**Done when** a branch whose plan has a `parent:` reports its step
position, a feature with no branches yet reports step 1 as next, and a
branch with no parent is unchanged from today.

### 8 · `notebooks` — closes finding 7

§07's notebook table makes three commitments; one is built. Split into
four independently shippable pieces — this is the largest step and does
not have to land as one PR:

| | Commitment | Status |
|---|---|---|
| a | Propose `pytest --nbval-lax` when notebooks are seen | **done** (`_config.suggest_verify_command`) |
| b | Hand the reviewer the jupytext `.py`, or extract code cells | missing |
| c | Count **code cells changed** rather than lines for `.ipynb` | missing |
| d | Notice tracked `.ipynb` with neither tool configured, once | missing |

- **8b/8c share one primitive.** A `_notebook.py` in both hooks and
  `canon_mcp` — the "about fifteen lines of standard-library JSON,
  `cell["source"]` where `cell_type == "code"`" §07 sizes it at.
- **8b**: `canon_review` gains a `notebooks` field naming, per changed
  `.ipynb`, either the paired jupytext `.py` or the extracted source,
  with a note saying which — so `execution_count` churn is never filed as
  a finding. Returned inline in the tool result; nothing is written to
  the repository.
- **8c**: `canon_position`'s diff summary and `canon_review` count
  changed code cells for `.ipynb` paths.
- **8d**: `session_start.py` checks for an `nbstripout` filter in
  `.gitattributes` or a jupytext config, and says so once per session
  with the fix. **Recommends, never installs** — same rule as branch
  protection.

**Done when** each of b, c and d has a test against a real small
`.ipynb` fixture, and Canon still never rewrites, strips or renders a
notebook.

### 9 · *withdrawn* — `async-headless-test`

Was: a real headless `claude -p` run asserting `async` mode denies with
its question surfaced, per Phase 2's "tested against a real headless run
rather than assumed."

**Withdrawn by the developer**, not deferred: a test that needs an API
key in CI is not suited to Canon at its current stage. Finding 9 stands
as a known gap rather than a closed one -- `async` mode keeps its unit
coverage (config parsing, and `plan_gate` denying rather than asking)
and remains unexercised against a real headless session.

The mode itself is deliberately kept. Removing it would be worse than
leaving it untested: without `async`, a headless or Slack run falls back
to `ask`, which §07 records degrades silently to *deny with no
explanation* when there is no interactive terminal -- the exact harness
sharp edge Canon exists to absorb.

### 10 · `docs-and-status` — housekeeping

- `src/canon_mcp/canon_mcp/plan.py`'s module docstring still says the
  `frame` skill is *"not built yet"*. It shipped.
- The README's Status section claims Phases 0–2 done without
  qualification. Once steps 1–9 land it is accurate; until then it is one
  layer optimistic. Update it **last**, so it never describes work that
  has not landed.
- Add `.canon/config.json` to this repository (`{"verify": "just test"}`)
  so Canon gates its own development. Do this only after step 3, or the
  currently-ungated hooks start firing on unrelated work mid-series.

## Decisions

Three points in this series are genuine choices with a live alternative,
and each gets a record under `docs/decisions/` at the step that settles
it rather than being decided by whichever code is written first:

- **What "inert" excludes** (step 3). `stop.py`'s first-run block and
  `session_start`'s injection stay live. The alternative — literally the
  whole plugin — makes an inert Canon indistinguishable from a broken
  one and removes the only path to configuring it.
- **`ship` still blocks on a missing required section** (step 6), even
  though §06 says a plan is never rejected. The plan and the pull request
  are different gates with different authority.
- **Steps name their branch slug** (step 7). The alternative, matching
  step prose against branch names, is wrong-but-plausible by
  construction.
