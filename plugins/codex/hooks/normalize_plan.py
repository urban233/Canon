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
"""

from __future__ import annotations

from pathlib import Path

import _common
import plan_header

_EDIT_TOOL_NAMES = (None, "Edit", "Write", "apply_patch")


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


def _normalize_branch_plan(root: Path, branch: str, path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    body = _existing_body(text)
    header, missing = plan_header.derive_branch_header(root, branch, body)
    new_text = header + "\n\n" + body.strip("\n") + "\n"
    if new_text == text:
        return  # already normalized; avoid rewriting what we just wrote
    path.write_text(new_text, encoding="utf-8")
    if missing:
        plan_relative = f"{plan_header.plans_dir_relative()}/{branch}.md"
        _common.context(
            "PostToolUse", plan_header.missing_sections_message(plan_relative, missing)
        )


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
    features_prefix = plan_header.feature_plans_dir_relative() + "/"

    for raw_path in touched:
        relative = _relative_path(root, raw_path)
        if relative is None or not relative.startswith(plans_prefix):
            continue
        absolute = root / relative
        if relative.startswith(features_prefix):
            _normalize_feature_plan(absolute)
            continue
        # A branch plan's own name is the branch it belongs to -- derive
        # it from the path rather than assuming it matches the current
        # branch, since the write may have targeted any branch's file.
        branch = relative[len(plans_prefix) : -len(".md")] if relative.endswith(".md") else None
        if branch:
            _normalize_branch_plan(root, branch, absolute)


if __name__ == "__main__":
    _common.fail_open(main)()
