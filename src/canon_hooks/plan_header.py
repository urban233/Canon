# SPDX-License-Identifier: BSD-3-Clause
"""Deriving a saved plan's header from its body -- shared by every
platform's plan-persistence hook.

Every supported platform ends up with the same on-disk contract: a plan
lands at `.canon/plans/<branch>.md` (or `.canon/plans/features/<slug>.md`
for a feature plan) as a small derived `---`-delimited header followed by
the plan body verbatim (see docs/plan.md §06). What differs per platform is
*how* the hook learns an approval happened and gets hold of the body text
in the first place -- Claude Code's `ExitPlanMode` tool call hands it over
directly; Codex has no such tool, so its hook instead reacts to the agent
writing the file itself and re-derives the header from whatever body is
already on disk. That trigger-and-body-acquisition step is platform-specific
and lives in each plugin's own `save_plan.py` (Claude) or `normalize_plan.py`
(Codex). Everything downstream of "I have a body of plan markdown, and
possibly a repository root and branch to derive from" is identical, and
lives here so a fix to how `## Scope` is parsed, say, lands on every
platform in one commit.

The header fills in only what's genuinely derivable and leaves the rest
blank rather than inventing it -- per docs/plan.md §06's own rule.

`verify:` is deliberately *not* copied from `.canon/config.json`. Once
§07's "overrides it for that branch" is honoured, a copy taken at approval
time stops being a record and becomes a pin: every later edit to the
repository's own verify command would be silently ignored on every branch
whose plan predates it. So the field is written only when the plan states
an override itself, and is otherwise left blank for the config to answer.

A missing required section is surfaced to the caller (as a one-time
message to relay, never a block) rather than silently recorded: §06 says
the hook "asks, once" and never rejects the plan, so the plan is written
first and the ask goes out as extra context. Feature plans are exempt --
`## Verification` has no meaning for a document that describes no branch.

One consequence of the plain `<branch>.md` formula deserves its own
paragraph, because it is not obvious from §06's own examples: a branch
named `features/<x>` reduces to exactly the same relative path
`feature_plan_path` gives a feature plan titled `<x>` --
`.canon/plans/features/<x>.md`. Saving there would silently overwrite
that feature plan, or be silently overwritten by one saved later, which
is exactly the failure Invariant II (docs/plan.md §04 -- position is
derived, never stored, so nothing can silently diverge from git) exists
to rule out everywhere else. So `branch_plan_path` treats the whole
`features/` prefix as reserved and redirects a colliding branch to
`.canon/plans/branches/<branch>.md` instead -- a third, narrower location
than §06 describes, used only for this one case -- and the caller is
expected to say so via `branch_namespace_collision_message`, once, the
same "already written, this can only add context" posture as
`missing_sections_message`. `feature/<x>` (singular -- the far more
common convention for a single feature branch) does not collide: its
first path segment is `feature`, a different directory entry from
`features` entirely.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import _common

_PLANS_DIR_RELATIVE = ".canon/plans"
_FEATURE_PLANS_DIR_RELATIVE = ".canon/plans/features"
_BRANCH_PLAN_COLLISION_DIR_RELATIVE = ".canon/plans/branches"
# The one path segment `feature_plan_path` ever writes under -- see the
# module docstring's paragraph on the reserved "features/" prefix.
_RESERVED_BRANCH_PLAN_SEGMENT = "features"

_REQUIRED_SECTION_LABELS = {
    "non-goals": "Non-goals",
    "verification": "Verification",
}
# Why each required section is required -- §06's rule is that "a section
# is required only if something actually reads it", so the ask names the
# reader rather than asserting the requirement.
_REQUIRED_SECTION_READERS = {
    "non-goals": (
        "the scope check reads it on every edit, and the reviewer reads it "
        "so a deliberate omission is never written up as a gap"
    ),
    "verification": (
        "it states what counts as done, and a lone backticked command on "
        "its first line sets this branch's verify: override"
    ),
}
_H1_HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
# Heading aliases: plan drafting phrases these a few ways, and the point is
# to read back what it already wrote rather than impose one spelling.
_SCOPE_SECTION_KEYS = ("scope", "in scope", "files")
_DONE_SECTION_KEYS = ("done", "definition of done", "done when")
_PARENT_SECTION_KEYS = ("parent", "parent plan", "feature")
_VERIFICATION_SECTION_KEYS = ("verification",)
_BULLET_PREFIX = re.compile(r"^[-*+]\s+")
_BACKTICKED = re.compile(r"`([^`]+)`")
_LONE_BACKTICKED = re.compile(r"^`([^`]+)`$")
# A path or glob has no whitespace in it. This is what keeps prose out of
# `scope:` -- see `scope_patterns`.
_PATH_TOKEN = re.compile(r"^[A-Za-z0-9_./*?\[\]{}-]+$")
_MAX_SCOPE_PATTERNS = 40
_MAX_DONE_CHARS = 200
_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 60


def missing_required_sections(body: str) -> list[str]:
    """Which of the two required sections (`## Non-goals`, `##
    Verification`) are absent or empty in `body`."""
    sections = _common.plan_sections(body)
    return [name for name in _REQUIRED_SECTION_LABELS if not sections.get(name)]


def is_feature_plan_body(body: str) -> bool:
    """Whether `body` is a feature plan -- has a non-empty `## Steps`
    section -- rather than a branch plan.

    The one disambiguator `save_plan.py` uses to route between
    `feature_plan_path` and `branch_plan_path`. `normalize_plan.py` needs
    it too: a file physically sitting under `.canon/plans/features/` is
    no longer provably a feature plan just because of where it is, now
    that a branch under the reserved "features/" prefix can land there
    first, before Canon ever gets a chance to redirect it (see the module
    docstring). Shared here so both platforms agree on the one signal
    that settles it.
    """
    return bool(_common.plan_sections(body).get("steps", "").strip())


def missing_sections_message(plan_relative: str, missing: list[str]) -> str:
    """The one-time ask for required sections that were not in the plan.

    docs/plan.md §06: "At save time the hook checks only that the two
    required ones are present and non-empty. Missing -> it asks, once. It
    never rejects a plan." The plan is already written by the time this is
    built -- this adds context, it cannot and must not block.
    """
    named = " and ".join(f"## {_REQUIRED_SECTION_LABELS[name]}" for name in missing)
    reasons = "; ".join(_REQUIRED_SECTION_READERS[name] for name in missing)
    return (
        f"Canon saved this plan to {plan_relative}, but {named} is missing "
        f"or empty. It matters because {reasons}. Add it to the saved plan "
        "now, asking the developer what belongs there if it is not obvious "
        "-- otherwise `canon_ship` will report it as missing when this "
        "branch is ready for a human. The plan itself is saved either way; "
        "Canon mentions this once."
    )


def branch_namespace_collision_message(branch: str) -> str:
    """The one-time note for a branch plan redirected out of the
    feature-plan namespace -- see the module docstring's paragraph on the
    reserved "features/" prefix, and `branch_plan_collides_with_feature_
    namespace`.

    Same posture as `missing_sections_message`: the plan is already
    written, at the path this message itself names, by the time this is
    built. This only adds context; it never withholds the save or asks
    for confirmation.
    """
    return (
        f"Canon saved this branch's plan to {branch_plan_relative(branch)} "
        f"instead of .canon/plans/{branch}.md, because '{branch}' starts "
        'with "features/", the prefix feature plans live under -- '
        "writing there would silently overwrite a feature plan of the "
        "same name, or be silently overwritten by one saved later. The "
        "plan itself is saved either way; Canon mentions this once. If "
        'this branch was never meant to imply a feature plan, consider '
        'renaming it off the "features/" prefix.'
    )


def _yaml_scalar(value: str | None) -> str:
    if not value:
        return ""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _header_line(key: str, value: str | None) -> str:
    scalar = _yaml_scalar(value)
    return f"{key}: {scalar}" if scalar else f"{key}:"


def _slugify(text: str) -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", text.lower()).strip("-")
    return slug[:_MAX_SLUG_LENGTH].strip("-") or "feature"


def feature_slug(body: str) -> str:
    """A filename-safe slug derived from the draft's own `# ` title, or
    "feature" if none is present -- a feature plan is expected to always
    include one, so this is a fallback, not the common case."""
    match = _H1_HEADING_PATTERN.search(body)
    return _slugify(match.group(1)) if match else "feature"


def _section_text(sections: dict[str, str], keys: tuple[str, ...]) -> str:
    """The first non-empty section among `keys`, or ""."""
    for key in keys:
        value = sections.get(key, "").strip()
        if value:
            return value
    return ""


def _clean_token(raw: str) -> str:
    """Strip one bullet, surrounding backticks and trailing punctuation."""
    token = _BULLET_PREFIX.sub("", raw.strip()).strip()
    return token.strip("`").strip().rstrip(",.;").strip()


def _scope_patterns(section: str) -> list[str]:
    """Glob patterns read out of a `## Scope` section.

    Deliberately conservative, because a wrong `scope:` is worse than an
    absent one: `check_scope.py` reports every path outside it as a
    departure, so one bad pattern turns a correct edit into a warning on
    every save. A token is accepted only if it could actually be a path --
    no whitespace in it -- which is what keeps a prose line like "this
    touches the slug module" out of the header entirely. Where a line
    carries backticked spans those are taken as the candidates, so
    "- `src/slugs/**` -- the slug module" yields the pattern and drops the
    commentary.

    Nothing is inferred from git: at approval time the branch may have no
    changes yet to infer from.
    """
    patterns: list[str] = []
    for line in section.splitlines():
        quoted = _BACKTICKED.findall(line)
        candidates = quoted if quoted else _clean_token(line).split(",")
        for candidate in candidates:
            token = _clean_token(candidate)
            if not token or not _PATH_TOKEN.match(token):
                continue
            if token not in patterns:
                patterns.append(token)
    return patterns[:_MAX_SCOPE_PATTERNS]


def _done_line(section: str) -> str | None:
    """The first line of a `## Done` section, as a single-line scalar."""
    for line in section.splitlines():
        token = _clean_token(line)
        if token:
            return " ".join(token.split())[:_MAX_DONE_CHARS]
    return None


def _verify_override(section: str) -> str | None:
    """A per-branch `verify:` override read out of `## Verification`.

    Recognised only in one exact shape: the section's first non-empty
    line consisting of a single backticked span, e.g.

        ## Verification
        `pytest tests/slugs/ -x`

        Confirm the new test fails without the fix.

    Anything else -- prose, a bare line, several commands -- yields None.
    docs/plan.md §07's rule is that wrong-but-plausible is worse than
    absent, and this is the field that decides which command gates every
    turn end on this branch: guessing a command out of a sentence is
    exactly the failure that rule exists to prevent.

    Note the asymmetry with `scope:`/`done:`: those are derived from a
    section that describes the same thing the field holds, so reading
    them back is recovery. A `verify:` override is a *deviation* from the
    repository's answer, so it has to be stated deliberately rather than
    inferred.
    """
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _LONE_BACKTICKED.match(stripped)
        return match.group(1).strip() or None if match else None
    return None


def _parent_path(root: Path, section: str) -> str | None:
    """A `## Parent` section resolved to a feature plan that exists.

    Written in §06's own form -- `features/<slug>.md`, relative to
    `.canon/plans/` -- and only when that file is really there. An
    unresolvable parent is left blank rather than written as a dangling
    link: `canon_plan` and `canon_position` both follow this field, and a
    link to nothing is worse than no link. That does mean a typo goes
    unreported here; surfacing it belongs with the other save-time
    feedback rather than in this function.
    """
    for line in section.splitlines():
        token = _clean_token(line)
        if not token:
            continue
        candidate = token.split("/")[-1]
        if not candidate.endswith(".md"):
            candidate += ".md"
        if (root / _FEATURE_PLANS_DIR_RELATIVE / candidate).is_file():
            return f"features/{candidate}"
        return None
    return None


def format_feature_header() -> str:
    return "\n".join(["---", "status: approved", "steps:", "---"])


class BranchHeaderFields(NamedTuple):
    header: str
    missing: list[str]


def derive_branch_header(
    root: Path, branch: str | None, body: str
) -> BranchHeaderFields:
    """The `---`-delimited header for a branch plan, derived from `body`
    and the repository's current git state.

    `branch` is only used to look up `_common.default_branch`/
    `_common.merge_base`'s inputs indirectly via `root` -- callers that
    already know the branch pass it for clarity; it does not otherwise
    change what is derived. Returns the header text plus the list of
    required sections that were missing, so a caller can decide whether to
    surface `missing_sections_message`.
    """
    del branch  # kept in the signature for callers' clarity; derived below
    default_branch = _common.default_branch(root)
    base = _common.merge_base(root, default_branch)

    missing = missing_required_sections(body)
    notes = [
        f"{_REQUIRED_SECTION_LABELS[name]} section is missing or empty"
        for name in missing
    ]

    sections = _common.plan_sections(body)
    lines = [
        "---",
        "status: approved",
        _header_line("base", base),
        _header_line(
            "scope",
            (
                "[" + ", ".join(scope) + "]"
                if (
                    scope := _scope_patterns(
                        _section_text(sections, _SCOPE_SECTION_KEYS)
                    )
                )
                else None
            ),
        ),
        _header_line("done", _done_line(_section_text(sections, _DONE_SECTION_KEYS))),
        _header_line(
            "verify",
            _verify_override(_section_text(sections, _VERIFICATION_SECTION_KEYS)),
        ),
        _header_line(
            "parent", _parent_path(root, _section_text(sections, _PARENT_SECTION_KEYS))
        ),
    ]
    if notes:
        lines.append(_header_line("notes", "; ".join(notes)))
    lines.append("---")
    return BranchHeaderFields(header="\n".join(lines), missing=missing)


def branch_plan_collides_with_feature_namespace(branch: str) -> bool:
    """Whether `branch` reduces, via the plain `<branch>.md` formula, to
    a path inside `.canon/plans/features/` -- the one directory
    `feature_plan_path` also writes to. See the module docstring's
    paragraph on the reserved "features/" prefix.

    A prefix check, not an existing-file check: the whole "features/"
    segment is reserved, not just the slugs a feature plan happens to
    occupy today, since a branch plan written under it now would collide
    just as fatally with a feature plan of the same name saved later.
    `branch == "features"` (no further segment) does *not* collide --
    that reduces to the sibling file `.canon/plans/features.md`, not to
    anything inside the `features/` directory.
    """
    head, _, rest = branch.partition("/")
    return head == _RESERVED_BRANCH_PLAN_SEGMENT and bool(rest)


def branch_plan_relative(branch: str) -> str:
    """The path `branch_plan_path` writes to, relative to the repo root,
    as a string -- for building a message without needing `root`."""
    base = (
        _BRANCH_PLAN_COLLISION_DIR_RELATIVE
        if branch_plan_collides_with_feature_namespace(branch)
        else _PLANS_DIR_RELATIVE
    )
    return f"{base}/{branch}.md"


def branch_plan_path(root: Path, branch: str) -> Path:
    # `branch` may contain "/" (e.g. "feature/widget"), so the plan's own
    # parent directory -- not just .canon/plans/ itself -- needs creating
    # by the caller before writing.
    #
    # A branch under the reserved "features/" prefix is redirected to
    # `.canon/plans/branches/<branch>.md` instead of the usual
    # `.canon/plans/<branch>.md` -- see `branch_plan_relative` and the
    # module docstring for why.
    return root / branch_plan_relative(branch)


def feature_plan_path(root: Path, slug: str) -> Path:
    return root / _FEATURE_PLANS_DIR_RELATIVE / f"{slug}.md"


def plans_dir_relative() -> str:
    return _PLANS_DIR_RELATIVE


def feature_plans_dir_relative() -> str:
    return _FEATURE_PLANS_DIR_RELATIVE


def branch_plan_collision_dir_relative() -> str:
    return _BRANCH_PLAN_COLLISION_DIR_RELATIVE
