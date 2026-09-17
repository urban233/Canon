# A release workflow with the gate where the drift is

Canon has eleven version strings and nothing that checks they agree.
`just ci` is green today with mismatched versions. This adds the check,
and a release workflow that derives the version rather than taking a
human's word for it.

## Why

Estimating the bump for 0.1.0 produced "six version strings"; the tree
had eleven. Nothing in the repository would have caught that being
wrong. Eight are hand-edited and three are generated -- and only the
generated three are guarded, by `sync-check`. That is the same shape as
the two enumeration bugs this repo already carries scars from: the CI
workflow that hand-copied `just ci`'s recipe list and omitted
`sync-check`, and the skills guard that iterated a hardcoded list of
four and stayed silent about a fifth.

So the valuable artifact here is not the tag. It is the check that makes
merging a release meaningful.

## Scope

- `tools/check_versions.py`
- `Justfile`
- `.github/workflows/release.yml`
- `BUILD.bazel`
- `pyproject.toml`

## Done

`just ci` fails when any version-bearing file disagrees with the others
or with the CHANGELOG's newest entry, and a release is cut by pressing
one button that reads the version from the repository.

## Parent

release-0-1-0.md

## Approach

1. `tools/check_versions.py` **discovers** version-bearing files by
   pattern rather than iterating a hardcoded list -- the direct lesson
   of the skills guard. A manifest added later is covered the day it
   lands, not the day someone remembers to add it.
2. `version-check` recipe, wired into `ci`.
3. Perturb one version, watch it go red, restore. A guard never seen to
   fail is not evidence.
4. `.github/workflows/release.yml` on `workflow_dispatch` only: read the
   version from the repository, refuse if it disagrees with the
   CHANGELOG, refuse if the tag exists, tag, and create a **draft**
   release. Never publish.
5. Close #66 in the same branch: this adds a second `tools/*.py`, and
   landing it into the same typecheck blind spot would make that gap
   worse rather than leaving it where it was.

## Non-goals

- **No automatic release on merge.** Whether marketplace installs pin to
  a tag or track the default branch is unestablished; if they pin,
  auto-tagging on merge is auto-publishing. `workflow_dispatch` is
  correct under both, and costs one click.
- **No published release, ever, from CI.** A draft is invisible;
  publishing is the outward-facing act and stays a human's.
- **No conventional-commit version derivation.** The version is decided
  by a human in a release PR; this only checks it is stated
  consistently.
- **No generated CHANGELOG.** It is written for adopters, by hand.
- **No change to what `sync-check` covers.** Generated version strings
  stay its job; this checks agreement, not synchronisation.

## Verification

`bazel test //tests/...` plus the perturbation in step 3, run once per
file class (a JSON manifest, a pyproject, MODULE.bazel, the CHANGELOG).
The release workflow itself cannot be exercised without cutting a
release, so its refusals are unit-tested against the script instead.
