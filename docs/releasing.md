# Releasing Canon

Cutting a release is two decisions by a human and everything else by the
repository. You decide *whether*; the machine decides *what*.

| Step | Who decides | Reversible? |
|---|---|---|
| `just version-check` passes | machine | a precondition, not a decision |
| **Merge the release pull request** | **you** | if installs track `main`, this is the publish |
| Tag and draft the release | machine, when you press the button | a draft is visible only to writers |
| **Publish the release** | **you** | no -- watchers are notified, it enters feeds |

Nothing in CI ever publishes. The workflow creates a *draft*; making it
public stays a click, the same line Canon holds on pull requests.

## Cutting a release

### 1. Decide the version

Canon is pre-1.0, so a release may change behaviour an install depends
on -- `CHANGELOG.md` says so at the top, deliberately. Until 1.0, bump
the minor for anything a user would notice and the patch for fixes that
change nothing about how Canon is used.

### 2. Open the release pull request

Branch from `main` as `chore/release-<version>`, with dots as dashes:

```sh
git switch main && git pull
git switch -c chore/release-0-2-0
```

Nine files state the version by hand. This list is a convenience, not
the authority -- `python3 tools/check_versions.py` **discovers** every
version-bearing file rather than enumerating them, so run it after
editing and believe it over this list if the two disagree (a hardcoded
enumeration is a failure this repository has already hit twice):

```
pyproject.toml
src/canon_mcp/pyproject.toml
MODULE.bazel
plugins/claude/.claude-plugin/plugin.json
plugins/codex/plugin.json
plugins/antigravity/plugin.json
plugins/canon-companion/.claude-plugin/plugin.json
.claude-plugin/marketplace.json          (two entries: claude, canon-companion)
```

The rest are generated and must not be hand-edited -- the companion's
Codex manifest and each plugin's vendored `canon_mcp` pyproject:

```sh
just sync-manifests
just sync-mcp
```

Then add the version's section to `CHANGELOG.md`, newest first, with its
link reference at the foot of the file. **Write it for someone deciding
whether to adopt Canon**, not for someone reading the commit log: what
changed for them, and what still does not work. The release notes the
workflow publishes are this section, read verbatim -- there is no second
copy to keep in step.

Finish with:

```sh
just ci
```

`version-check` is part of `ci`, so a missed file fails here rather than
after the tag exists.

### 3. Merge it

**This is the first human gate.** Merging decides that this code becomes
what users get. If marketplace installs track the default branch -- which
is likely, though not confirmed for either CLI -- then merging *is* the
publish, and everything after it is labelling.

Merge it yourself. Canon never merges a pull request, including its own
release.

### 4. Run the release workflow

GitHub → **Actions** → **Release** → **Run workflow**, on `main`.

It takes no inputs, on purpose. The version is read from the repository;
a human typing a version into a form is exactly the hand-copied
enumeration this repository has twice been bitten by. The workflow:

1. runs `just version-check` again -- it can be dispatched from any ref,
   including one CI never saw green;
2. reads the version with `python3 tools/check_versions.py --print`;
3. refuses if that tag already exists;
4. reads the notes with `python3 tools/check_versions.py --notes`;
5. creates the annotated tag `v<version>` and pushes it;
6. creates a **draft** release and prints its URL.

### 5. Publish the draft

**This is the second human gate.** Open the URL the workflow printed,
read the notes as a stranger would, and press **Publish release**.

A bad draft costs you a delete. A bad publish notifies everyone
watching.

## When the gate refuses

`just version-check` names the file and the disagreement. The three
things it says:

**`versions disagree: 0.1.0, 0.2.0`**, then every file and its version.
Something was missed, or a generated copy was edited by hand. Re-run
`just sync-manifests` and `just sync-mcp` before assuming it is a file
you forgot.

**`CHANGELOG.md's newest entry is X, but every manifest declares Y`**.
Either the bump or the changelog entry is missing. Note that a
`## [Unreleased]` heading is not read as a version claim -- a repository
mid-cycle is not broken.

**`CHANGELOG.md names no released version`**. There is no `## [X.Y.Z]`
heading at all.

The check *discovers* version-bearing files rather than iterating a
list, so a plugin added later is covered the day it lands. This is the
one design decision in `tools/check_versions.py` worth preserving if it
is ever rewritten: a hardcoded list here goes stale silently, which is
the only way that matters. The repository has been bitten by exactly
that twice -- once when `.github/workflows/ci.yml` hand-copied `just
ci`'s recipe list and omitted `sync-check`, once when the skills drift
guard iterated four names and said nothing about a fifth.

## What is deliberately not automated

**No release on merge.** The workflow is `workflow_dispatch` only.
Whether a marketplace install pins to a tag or tracks the default branch
is unestablished for both CLIs; if it pins, then tagging on merge is
publishing without anyone deciding to. A button press is correct under
either, and costs one click. If someone establishes the answer, record
it in `docs/codex-hook-surface.md` -- that file is where this project
keeps the line between what was confirmed and what was inferred -- and
revisit this.

**No version derived from commit messages.** A human picks the version
in the release pull request. This machinery only proves it is stated
consistently.

**No generated changelog.** It is written for adopters, by hand.

**No published release from CI, ever.**

## If something goes wrong

**The tag is wrong but the draft is not published.** Delete the draft
and the tag, fix the branch, dispatch again:

```sh
gh release delete v0.2.0 --yes
git push --delete origin v0.2.0
git tag -d v0.2.0
```

**Canon's own git guard will refuse the middle command.**
`_DESTRUCTIVE_PATTERNS` matches `git push ... --delete` without
distinguishing a tag from a branch, so deleting a mistaken release tag
is reported as "a remote branch deletion" and blocked. That is the guard
being conservative rather than wrong -- but it means deleting the tag
has to happen outside a Canon-gated session, or through the GitHub UI
(Releases → Tags → delete). Do not reach for a bypass flag to get around
it.

**The release is already published.** Do not move the tag -- someone may
have installed from it. Fix forward with a patch release.
