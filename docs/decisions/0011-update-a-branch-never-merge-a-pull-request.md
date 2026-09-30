# 0011. Update a branch; never merge a pull request

## Context

§12's table lists "`merge`, `rebase` onto a shared branch, `push
--force`, `reset --hard`, branch delete, tag" as **never**, and
`git_guard.py` implemented the `merge` and `push --force` parts as
blanket rules. Any `git merge` was denied, and so was any push carrying
`--force`, a pattern that also matched `--force-with-lease`.

The table's own reason is narrower than its rule: "each either rewrites
shared history or destroys work." Recorded sessions show the blanket
rule refusing commands that do neither:

- `git merge --ff-only origin/win/harness-render-path` (2026-09-20)
  only fast-forwards a local branch to its own remote.
- `git merge --no-edit origin/main` into `feat/m1` (2026-09-30) brings
  a pull request's branch up to date with its base.
- `git push --force-with-lease origin feat/gl-image-harness-2`
  (2026-09-20) publishes a rebased branch that nobody else pushes to,
  and refuses if someone did.

Each is how a branch is kept current, and a stacked branch needs them
most: when its parent step moves, the child must take the parent in
(merge) or be replayed onto it (rebase, then a lease push). Denying all
three turned every parent update into a hand-off to the developer.

## Decision

**A merge or a force push is judged by the branch it lands on.**

- **On a feature branch**, `git merge` of anything is allowed. So is
  `git push --force-with-lease` (or `--force-if-includes`) to that
  branch.
- **On the default branch**, `git merge` is denied unless it is
  `--ff-only` from the branch's own remote (`origin/<default>`, `@{u}`).
  `git pull` naming another branch is denied too, since it is the same
  local merge by another verb. A lease push that targets the default
  branch, or `--all`/`--mirror`, is denied.
- **Everywhere**, a plain force push is still denied: `--force`, `-f`
  in any short-flag cluster, or a `+refspec`. So are `gh pr merge`,
  `gh pr close` and an approving review. Merging a pull request stays
  what §12 calls "the only real gate in the whole system", and it
  stays a human's.

The branch a command lands on is the current branch, or the last `git
checkout`/`git switch` earlier in the same command, so `git checkout
main && git merge feature` is still caught. When the branch can't be
read (a detached or unborn HEAD, a `cd` elsewhere, `git -C`), the
command is not treated as landing on the default branch. A tripwire that
guessed "main" on uncertainty would deny ordinary work, and every Canon
gate fails open.

## Alternatives rejected

- **Allow updates only when the command names the default branch's
  remote** (`git merge origin/main`). That covers the base update but
  not a stacked child taking its parent step (`git merge movie-effects`),
  which is the case that prompted this.
- **Keep the blanket rule and tell developers to run updates
  themselves.** That is today's behaviour, and the recorded sessions
  show it stalling work that §12's own test, "can a human undo this in
  one click without losing work?", would allow. A merge into a feature
  branch is one `git reset` from undone, and a lease push refuses to
  overwrite work it hasn't seen.

## Consequences

- **§12's table now overstates the rule**, listing `merge` and `push
  --force` as never. The plan document is not edited to match the code,
  as with `0003`, `0005` and `0006`. This record is where that reader is
  meant to land.
- **This is still a tripwire, not a sandbox**, exactly as `git_guard.py`
  says of itself. A misread path checkout (`git checkout file.txt`
  without `--`) can make the guard believe HEAD moved, and a merge
  hidden in a multi-word quoted string passes, as it always has.
- **A `rebase` needs no rule change.** It was never on the guard's list.
  What made rebasing a stacked branch unusable was the push afterwards.
