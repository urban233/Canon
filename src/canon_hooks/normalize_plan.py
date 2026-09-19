# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PostToolUse` hook for an edit, scoped to `.canon/plans/` --
the plan, persisted, on a platform with no `ExitPlanMode`.

Claude Code's own plan-persistence hook (`save_plan.py`) has a trigger
that does not exist on Codex: an approved `ExitPlanMode` tool call, whose
`tool_response` hands the plan body over directly (see
docs/codex-hook-surface.md and save_plan.py's own docstring for why no
Codex equivalent could be found). Codex's `/plan` mode drafts a plan but
is not documented to write it anywhere a hook could read, so this
plugin's own `plan`/`frame` skills instead instruct the agent to write
the approved plan itself, to `.canon/plans/<branch>.md` (a branch plan)
or `.canon/plans/features/<slug>.md` (a feature plan) -- the same two
locations `save_plan.py` writes to, just reached by a different route.

This hook's job is narrower than `save_plan.py`'s as a result: it does
not need to *detect* an approval, because the write already only happens
once one occurred (per the skill's own instructions -- see
plugins/codex/skills/plan/SKILL.md). What it still must do is enforce
that the file's header is *derived*, never agent-authored, exactly as
docs/plan.md §06 requires on every platform: it re-reads whatever the
agent just wrote, treats everything after a pre-existing `---` header
block (if any -- an agent's own first draft may have none) as the body,
derives the canonical header from that body and the repository's git
state, and rewrites the file with the derived header in front. An agent
that hand-wrote a plausible-looking `scope:`/`done:`/`verify:` header of
its own is exactly the case this exists to correct -- docs/plan.md §07's
"wrong-but-plausible is worse than absent" applies as much to a header
the agent invented as to one this hook would have guessed.

Guards against re-entrancy: if the header this hook would derive is
already exactly what's on disk, it writes nothing, since `normalize_plan`
runs again on the write it itself performs.

This hook's own `main()` is the only thing in this plugin that genuinely
has no Claude Code counterpart; the header-derivation logic it calls into
lives in the shared `plan_header.py`, identical to what `save_plan.py`
uses on Claude Code.

One consequence of that is specific to this platform: the `plan` skill
tells the agent, literally, to write a branch plan to
`.canon/plans/<branch>.md` -- it has no knowledge of `plan_header.py`'s
reserved "features/" prefix (see that module's docstring), so a branch
named e.g. "features/public-permalinks" already landed at
`.canon/plans/features/public-permalinks.md` -- the same path a feature
plan of that slug uses -- by the time this hook is even invoked; unlike
`save_plan.py`, which picks the destination itself and so never writes
there in the first place. This hook cannot undo a write that already
happened, but it can still stop the collision from *staying*: anything
found under `.canon/plans/features/` -- matched case-insensitively, so
`.canon/plans/Features/` is recognised too (see
`_relative_is_under_features_prefix`; `plan_header.py`'s own
`branch_plan_collides_with_feature_namespace` compares the same way, for
the same reason -- macOS and Windows resolve the two paths to the same
file) -- with no non-empty `## Steps` section
(`plan_header.is_feature_plan_body`) is a candidate for having been a
colliding branch's plan rather than a feature plan.

A missing `## Steps` section is not proof, though -- a genuine feature
plan mid-draft, or one headed "## Steps (ordered)" rather than the exact
heading this hook looks for, reads the same way, and unlike the
in-place header rewrite this hook does everywhere else, "wrong" here
means *moving* a file and overwriting whatever the destination already
held. So a second, independent signal is required before a rescue
candidate is actually relocated: `_common.current_branch(root)` must
equal the branch its own path implies. The genuine rescue case survives
this -- the agent writes a branch's plan while standing on that branch
-- and a false-negative `## Steps` read on a plan for some *other*
branch (most commonly `main`, where a feature plan is drafted before any
branch exists) degrades to being left alone and normalized as a feature
plan in place, exactly as before this redirect existed, rather than
being exiled. And even a true rescue candidate is never allowed to
`replace()` an occupied destination -- if something is already saved
where `plan_header.branch_plan_path` would put it, this hook leaves the
candidate where it is and says so, instead of silently destroying
whatever was there.
"""

from __future__ import annotations

from pathlib import Path

import _common
import plan_header

_EDIT_TOOL_NAMES = (None, "Edit", "Write", "apply_patch")
# The one path segment `feature_plan_path` ever writes under, compared
# case-insensitively wherever a touched path's own segment is checked
# against it -- see `_relative_is_under_features_prefix` and
# plan_header.py's docstring on why the reserved-prefix check itself is
# case-insensitive.
_FEATURE_SEGMENT = plan_header.feature_plans_dir_relative().rsplit("/", 1)[-1]


def _relative_path(root: Path, file_path: str) -> str | None:
    try:
        return str(Path(file_path).resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return None


def _existing_body(text: str) -> str:
    """The part of `text` this hook should treat as the plan body.

    If the file already carries a `---`-delimited header (most often
    because this hook already normalized it once), that header is
    discarded and only the body is kept -- re-deriving from a body that
    still had the *previous* header glued to the front would duplicate
    it. A file with no such header (an agent's first, unnormalized
    draft) is taken as body in full.
    """
    _, body = _common.plan_header_and_body(text)
    return body


def _normalize_branch_plan(
    root: Path, branch: str, path: Path, *, extra_notice: str | None = None
) -> None:
    """Derive `path`'s header from its own body and rewrite it in place.

    `extra_notice`, when given, is folded into the same `additionalContext`
    call as the missing-sections ask rather than sent separately -- only
    one `_common.context` call can ever fire per hook invocation (it
    exits the process), so a caller with more than one thing to say has
    to say it in one call. Used by `_normalize_features_prefixed_path` to
    attach the one-time collision note to the very write that relocated
    the file, without losing the re-entrancy guard below for every write
    after that.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    body = _existing_body(text)
    header, missing = plan_header.derive_branch_header(root, branch, body)
    new_text = header + "\n\n" + body.strip("\n") + "\n"
    if new_text == text and extra_notice is None:
        return  # already normalized; avoid rewriting what we just wrote
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    notices = [extra_notice] if extra_notice else []
    if missing:
        notices.append(
            plan_header.missing_sections_message(
                plan_header.branch_plan_relative(branch), missing
            )
        )
    if notices:
        _common.context("PostToolUse", " ".join(notices))


def _normalize_feature_plan(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    body = _existing_body(text)
    new_text = plan_header.format_feature_header() + "\n\n" + body.strip("\n") + "\n"
    if new_text == text:
        return
    path.write_text(new_text, encoding="utf-8")


def _occupied_destination_message(branch: str) -> str:
    """The one-time note for a rescue candidate that was left in place
    because `plan_header.branch_plan_path` already has something saved
    at its destination.

    Never clobbers: `_normalize_features_prefixed_path` calls this
    instead of moving the file when `destination.exists()`, the same
    "already written, this can only add context" posture as every other
    message in this module -- see `plan_header.missing_sections_message`.
    """
    return (
        f"Canon left this branch's plan at .canon/plans/{branch}.md -- "
        f"the same path a feature plan of the same name would use -- "
        f"instead of moving it to {plan_header.branch_plan_relative(branch)}, "
        "because something is already saved there. Look at both and merge "
        "them by hand; Canon mentions this once."
    )


def _normalize_features_prefixed_path(root: Path, relative: str, path: Path) -> None:
    """A write under `.canon/plans/features/` -- normally a feature plan,
    but no longer provably so from its path alone (see the module
    docstring's paragraph on the reserved "features/" prefix, and on why
    a missing `## Steps` section alone is not enough to relocate it).

    A genuine feature plan (non-empty `## Steps`) is normalized in place,
    exactly as before. A file with no `## Steps` is relocated only when a
    second, independent signal agrees it is a colliding branch's plan:
    the repository's current branch must be the one its own path
    implies. Anything that fails either check -- has `## Steps`, or
    belongs to some other branch -- is left alone and normalized as a
    feature plan in place, the same as before this redirect existed.
    Even a confirmed rescue candidate is never moved onto an occupied
    destination; see `_occupied_destination_message`.
    """
    if not relative.endswith(".md"):
        _normalize_feature_plan(path)  # not a plan file this hook can parse
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    body = _existing_body(text)
    if plan_header.is_feature_plan_body(body):
        _normalize_feature_plan(path)
        return

    plans_prefix = plan_header.plans_dir_relative() + "/"
    branch = relative[len(plans_prefix) : -len(".md")]

    if _common.current_branch(root) != branch:
        # No `## Steps` doesn't prove this ISN'T a feature plan -- a
        # mid-draft one, or one headed differently
        # (e.g. "## Steps (ordered)"), reads the same way. Only relocate
        # when the write can be tied to the branch actually being worked
        # on; anything else degrades to "normalized as a feature plan in
        # place", not "moved and possibly overwrites the destination".
        _normalize_feature_plan(path)
        return

    destination = plan_header.branch_plan_path(root, branch)
    if destination == path:
        # Defensive only -- `branch` was derived from a path under
        # `.canon/plans/features/`, so `branch_plan_collides_with_
        # feature_namespace(branch)` is true by construction and
        # `branch_plan_path` always redirects it. Normalize in place
        # rather than silently doing nothing if that ever stops holding.
        _normalize_branch_plan(root, branch, path)
        return
    if destination.exists():
        # Never clobber: something is already saved at the redirect
        # target (e.g. a second write landed here after an earlier one
        # was already relocated). Leave this file where it is.
        _normalize_branch_plan(
            root, branch, path, extra_notice=_occupied_destination_message(branch)
        )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    path.replace(destination)
    _normalize_branch_plan(
        root,
        branch,
        destination,
        extra_notice=plan_header.branch_namespace_collision_message(branch),
    )


def _relative_is_under_features_prefix(relative: str, plans_prefix: str) -> bool:
    """Case-insensitive counterpart to `relative.startswith(features_
    prefix)`.

    `plan_header.branch_plan_collides_with_feature_namespace` compares
    case-insensitively, because macOS and Windows resolve
    `.canon/plans/Features/<x>.md` and `.canon/plans/features/<x>.md` to
    the same file. This dispatch has to agree: an agent's write to the
    capitalized path lands on that identical file, and if this check
    stayed exact-case, `_normalize_features_prefixed_path` -- and the
    collision check inside it -- would simply never run for it, leaving
    the write silently unexamined exactly as it was before this hook's
    redirect existed.
    """
    if not relative.startswith(plans_prefix):
        return False
    head = relative[len(plans_prefix) :].split("/", 1)[0]
    return head.casefold() == _FEATURE_SEGMENT


def _branch_for_plan_path(
    relative: str, plans_prefix: str, collision_prefix: str
) -> str | None:
    """The branch a plan path under `.canon/plans/` (but not
    `.canon/plans/features/`, handled separately) belongs to.

    A path under the collision-redirect root (`.canon/plans/branches/`)
    only means "strip that prefix instead" when what is left really is a
    "features/"-prefixed branch -- a genuine branch literally named
    "branches/<x>" (see plan_header.py's docstring on this residual
    overlap) writes its own, unrelated plan at this same shape of path,
    and stripping the redirect prefix there would derive "<x>" instead
    of the true branch "branches/<x>". `relative` is checked against
    both candidates, and `plan_header.branch_plan_collides_with_feature_
    namespace` decides which one is real.
    """
    if not relative.endswith(".md"):
        return None
    if relative.startswith(collision_prefix):
        candidate = relative[len(collision_prefix) : -len(".md")]
        if plan_header.branch_plan_collides_with_feature_namespace(candidate):
            return candidate
    return relative[len(plans_prefix) : -len(".md")]


def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        return
    if payload.get("tool_name") not in _EDIT_TOOL_NAMES:
        return
    touched = _common.edited_paths(payload)
    if not touched:
        return

    root = _common.repo_root(payload)
    plans_prefix = plan_header.plans_dir_relative() + "/"
    collision_prefix = plan_header.branch_plan_collision_dir_relative() + "/"

    for raw_path in touched:
        relative = _relative_path(root, raw_path)
        if relative is None or not relative.startswith(plans_prefix):
            continue
        absolute = root / relative

        if _relative_is_under_features_prefix(relative, plans_prefix):
            _normalize_features_prefixed_path(root, relative, absolute)
            continue

        # A branch plan's own name is the branch it belongs to -- derive
        # it from the path rather than assuming it matches the current
        # branch, since the write may have targeted any branch's file.
        branch = _branch_for_plan_path(relative, plans_prefix, collision_prefix)
        if branch:
            _normalize_branch_plan(root, branch, absolute)


if __name__ == "__main__":
    _common.fail_open(main)()
