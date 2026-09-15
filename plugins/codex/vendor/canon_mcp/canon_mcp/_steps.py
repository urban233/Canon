# SPDX-License-Identifier: BSD-3-Clause
"""Which step of a feature plan this branch is on -- derived, never stored.

docs/plan.md §06: "'which step am I on?' stays derived: `canon_position`
reads the parent's list, checks which branches exist and which PRs
merged, and computes the answer. Nothing is stored, so nothing can be
stale."

The one thing that needed deciding is how a line of `## Steps` is
matched to a branch. Fuzzy-matching step prose against branch names is
wrong-but-plausible by construction -- it would quietly report the wrong
step on any feature whose steps share vocabulary, which is most of them.
So the convention is explicit and `frame` now asks for it: each step
leads with its branch slug.

    ## Steps
    - slugs: make duplicate slugs raise
    - permalinks-api: expose the permalink endpoint

A step whose line carries no `slug:` prefix is still listed, still
counted, and simply reports `unmatched` -- an old feature plan written
before this convention degrades to "I can't tell you", never to a
confident wrong answer.

The second thing that needed deciding is how a step says what it waits
for. Reporting `current` as "the first step that has not merged" made
every feature strictly sequential by construction, and real ones are
not: this repository's own `phase-0-2-gap-closure.md` had to draw its
ten-branch stack as an ASCII diagram in prose, which `canon_position`
cannot read. So a step may name its dependencies:

    ## Steps
    - eval-corpus: 30 graded requests with expected outcomes
    - pymol-tools (after: none): expose cmd.* to an agent
    - baseline (after: eval-corpus, pymol-tools): record the score

A line with no `(after: ...)` depends on the step before it, which is
exactly what every plan written before this notation already meant --
so parallelism is opt-in and nothing already in a repository changes
meaning. An explicit list replaces that rule, and `(after: none)`
declares a step that waits for nothing.

Startability is a one-level question -- "has each direct dependency
merged?" -- so nothing here traverses the graph, and transitivity falls
out for free: a step blocked behind an unmerged step is blocked whether
or not the step further back has landed. Cycles therefore cannot hang
anything; they are detected only so that `a (after: b)` with
`b (after: a)` reports itself instead of silently showing nothing as
startable forever.

A dependency naming a slug no step has is reported rather than ignored,
and blocks, for the same reason an unmatched step does: not knowing is
an answer, and guessing is not.

`merged` is read from the pull request rather than from the branch,
because a repository with "automatically delete head branches" enabled
has no branch left to inspect once a step lands. Branch existence is
only ever evidence that a step has *started*.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# No leading whitespace: an indented bullet is a sub-point of a step, not
# a step. And a `###` heading ends the list -- a `## Steps` section that
# carries per-step detail in subsections would otherwise contribute every
# bullet in that prose. Both were found by pointing this at Canon's own
# feature plan, which reported 30 steps.
_STEP_LINE = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
_SUBSECTION = re.compile(r"^#{3,}\s")
# `(after: ...)` sits between the slug and its colon, so a line without
# one still matches exactly as it did before the group existed. The
# group is deliberately not greedy about what it accepts: only the
# literal word `after` opens it, so `- slug (the hard one): ...` fails
# the whole pattern and reports `unmatched` -- which is what it did
# before this too.
_SLUG_PREFIX = re.compile(
    r"^`?([A-Za-z0-9][A-Za-z0-9._/-]*)`?"
    r"(?:\s*\((?i:after)\s*:\s*([^)]*)\))?"
    r"\s*:\s*(.*)$"
)
_NO_DEPENDENCIES = "none"
_MAX_STEPS = 100

STATUS_MERGED = "merged"
STATUS_OPEN = "open"
STATUS_STARTED = "started"
STATUS_NOT_STARTED = "not started"
STATUS_UNMATCHED = "unmatched"


def _clean_slug(token: str) -> str:
    return token.strip().strip("`").strip()


def _dependencies(declared: str | None, previous_slug: str | None) -> list[str]:
    """The slugs a step waits for.

    `declared` is None when the line carried no `(after: ...)`, which
    means the implicit rule: this step waits for the one before it. That
    is what every plan written before this notation already meant, so
    none of them changes meaning and parallelism stays opt-in.

    A slugless predecessor contributes no dependency, because there is
    no slug to wait on and nothing could ever resolve it. Such a step is
    already reported `unmatched`, so the plan has already said it cannot
    be tracked -- this does not make that quieter.
    """
    if declared is None:
        return [previous_slug] if previous_slug else []
    slugs = [
        cleaned for token in declared.split(",") if (cleaned := _clean_slug(token))
    ]
    if len(slugs) == 1 and slugs[0].lower() == _NO_DEPENDENCIES:
        return []
    return slugs


def parse_steps(section: str) -> list[dict[str, Any]]:
    """The ordered `## Steps` entries, as
    `{index, slug, description, depends_on}`.

    `slug` is None for a line that does not lead with one -- the entry is
    kept rather than dropped, so the count stays honest.
    """
    steps: list[dict[str, Any]] = []
    previous_slug: str | None = None
    for line in section.splitlines():
        if _SUBSECTION.match(line):
            break
        match = _STEP_LINE.match(line)
        if not match:
            continue
        text = match.group(1)
        slug_match = _SLUG_PREFIX.match(text)
        if slug_match:
            slug: str | None = slug_match.group(1)
            declared: str | None = slug_match.group(2)
            description = slug_match.group(3).strip() or text
        else:
            slug, declared, description = None, None, text
        steps.append(
            {
                "index": len(steps) + 1,
                "slug": slug,
                "description": description,
                "depends_on": _dependencies(declared, previous_slug),
            }
        )
        previous_slug = slug
        if len(steps) >= _MAX_STEPS:
            break
    return steps


def _match_ref(slug: str, names: "Iterable[str]") -> str | None:
    """The ref named exactly `slug`, else one suffixed with `/slug` so a
    `feature/slugs` branch matches the step `slugs`.

    Applied to pull request head refs as well as to branches, and that
    is load-bearing rather than tidy: a repository with "automatically
    delete head branches" enabled has no branch left once a step lands,
    so the *only* surviving record is the pull request -- whose head ref
    carries the same prefix the branch did. Matching pulls by exact slug
    alone reported every completed step as `not started`, which is how
    this was found.
    """
    names = list(names)
    if slug in names:
        return slug
    suffix = f"/{slug}"
    matches = sorted(name for name in names if name.endswith(suffix))
    return matches[0] if matches else None


def annotate(
    steps: list[dict[str, Any]],
    branches: set[str],
    pulls: dict[str, dict[str, Any]],
    merged_branches: set[str],
) -> list[dict[str, Any]]:
    """Each step with a `status`, its `branch` and its `pull_request`.

    Pure: every fact about the repository arrives as an argument, so this
    is testable without a git repository or a `gh` login.
    """
    annotated: list[dict[str, Any]] = []
    for step in steps:
        entry = {**step, "branch": None, "pull_request": None}
        slug = step["slug"]
        if slug is None:
            entry["status"] = STATUS_UNMATCHED
            annotated.append(entry)
            continue
        branch = _match_ref(slug, branches)
        pull = pulls.get(branch) if branch else None
        if pull is None:
            head = _match_ref(slug, pulls)
            if head is not None:
                pull = pulls[head]
                branch = branch or head
        entry["branch"] = branch
        entry["pull_request"] = pull
        if pull is not None and pull.get("state") == "MERGED":
            entry["status"] = STATUS_MERGED
        elif branch is not None and _match_ref(branch, merged_branches) is not None:
            entry["status"] = STATUS_MERGED
        elif pull is not None and pull.get("state") == "OPEN":
            entry["status"] = STATUS_OPEN
        elif branch is not None:
            entry["status"] = STATUS_STARTED
        else:
            entry["status"] = STATUS_NOT_STARTED
        annotated.append(entry)
    return _resolve_dependencies(annotated)


def _resolve_dependencies(annotated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each step's `blocked_by` and `unknown_dependencies`, filled in.

    A second pass, because a step may legitimately name one listed after
    it -- `## Steps` is an ordered list of work, not a topological sort,
    and demanding the author produce one would be exactly the ceremony
    this notation exists to avoid.
    """
    by_slug = {step["slug"]: step for step in annotated if step["slug"]}
    for entry in annotated:
        unknown: list[str] = []
        blocked: list[str] = []
        for slug in entry["depends_on"]:
            target = by_slug.get(slug)
            if target is None:
                unknown.append(slug)
            elif target["status"] != STATUS_MERGED:
                blocked.append(slug)
        entry["unknown_dependencies"] = unknown
        entry["blocked_by"] = blocked
    return annotated


def _cycle_slugs(steps: list[dict[str, Any]]) -> list[str]:
    """Slugs whose dependencies form a cycle, so they can never become
    startable.

    Found by repeatedly removing steps that wait for nothing; whatever
    will not peel is in a cycle. Only edges pointing at steps that exist
    are considered -- an unknown dependency already blocks on its own
    and is not a cycle. This never runs to decide startability, which is
    a one-level question; it runs so a plan that contradicts itself says
    so instead of reporting an empty `startable` forever.
    """
    known = {step["slug"] for step in steps if step["slug"]}
    waiting = {
        step["slug"]: {slug for slug in step["depends_on"] if slug in known}
        for step in steps
        if step["slug"]
    }
    peeled = True
    while peeled:
        peeled = False
        for slug in [slug for slug, slugs in waiting.items() if not slugs]:
            del waiting[slug]
            for slugs in waiting.values():
                slugs.discard(slug)
            peeled = True
    return sorted(waiting)


def summarize(path: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The `feature` field `canon_position` returns.

    `current` is the first step that has not merged -- the honest reading
    of "which step am I on" for an ordered list. None when every step has
    landed, which is what "the feature is done" looks like. It keeps that
    exact meaning now that `startable` exists, so every existing reader
    of this shape is unaffected.

    `startable` is every step that has not been begun and whose direct
    dependencies have all merged -- the answer to "what could I pick up
    now", which an ordered list alone cannot give. A step with an
    unknown dependency is left out: Canon cannot tell whether it is
    ready, and saying nothing is the honest form of that.

    Deliberately, none of this reaches `canon_position`'s prose. "You are
    on step 2 of 4" is a claim about where the work stands; "steps 2 and
    4 are startable" is a different kind of claim, and putting it in the
    sentence every session reads would sound like an instruction to
    parallelise work that may have no reason to be parallel. It stays in
    the payload, for a caller that asked.
    """
    completed = sum(1 for step in steps if step["status"] == STATUS_MERGED)
    current = next(
        (step for step in steps if step["status"] != STATUS_MERGED),
        None,
    )
    startable = [
        step
        for step in steps
        if step["status"] == STATUS_NOT_STARTED
        and not step["blocked_by"]
        and not step["unknown_dependencies"]
    ]
    return {
        "path": path,
        "steps": steps,
        "current": current,
        "startable": startable,
        "cycle": _cycle_slugs(steps),
        "completed": completed,
        "total": len(steps),
    }
