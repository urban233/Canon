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
_SLUG_PREFIX = re.compile(r"^`?([A-Za-z0-9][A-Za-z0-9._/-]*)`?\s*:\s*(.*)$")
_MAX_STEPS = 100

STATUS_MERGED = "merged"
STATUS_OPEN = "open"
STATUS_STARTED = "started"
STATUS_NOT_STARTED = "not started"
STATUS_UNMATCHED = "unmatched"


def parse_steps(section: str) -> list[dict[str, Any]]:
    """The ordered `## Steps` entries, as `{index, slug, description}`.

    `slug` is None for a line that does not lead with one -- the entry is
    kept rather than dropped, so the count stays honest.
    """
    steps: list[dict[str, Any]] = []
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
            description = slug_match.group(2).strip() or text
        else:
            slug, description = None, text
        steps.append(
            {"index": len(steps) + 1, "slug": slug, "description": description}
        )
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
    return annotated


def summarize(path: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The `feature` field `canon_position` returns.

    `current` is the first step that has not merged -- the honest reading
    of "which step am I on" for an ordered list. None when every step has
    landed, which is what "the feature is done" looks like.
    """
    completed = sum(1 for step in steps if step["status"] == STATUS_MERGED)
    current = next(
        (step for step in steps if step["status"] != STATUS_MERGED),
        None,
    )
    return {
        "path": path,
        "steps": steps,
        "current": current,
        "completed": completed,
        "total": len(steps),
    }
