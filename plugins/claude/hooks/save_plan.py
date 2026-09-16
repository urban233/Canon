# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PostToolUse:ExitPlanMode` hook -- the plan, persisted.

Plan mode already reads the repository and drafts a plan; its one gap is
that the approved result lands in `~/.claude/plans/`, outside the
repository, swept after 30 days -- never reviewable in a PR, never
readable by a hook. This hook closes that gap the moment the developer
approves a plan: it saves it, verbatim, to `.canon/plans/<branch>.md`
with a small derived header (see docs/plan.md §06).

Confirmed directly from this project's own `ExitPlanMode` tool results
(not just documentation, which does not specify this at the needed
precision): an approved call's `tool_response` contains the literal
marker `"## Approved Plan:"` followed by the plan body, and usually a
`"Your plan has been saved to: <path>"` line pointing at the exact file
the developer approved on screen. This hook requires that marker before
doing anything -- its absence (declined, or "keep planning") makes the
hook a silent no-op, which is what keeps it correct regardless of
whether `PostToolUse` fires on every `ExitPlanMode` call or only on
approved ones.

Header derivation (what's genuinely derivable vs. left blank, the
`verify:` field's asymmetry with `.canon/config.json`, the one-time ask
for a missing required section, the feature-vs-branch-plan split on a
non-empty `## Steps` section, and the "features/"-prefixed branch that
would otherwise collide with the feature-plan namespace) all live in
`plan_header.py`, shared with Codex's `normalize_plan.py` -- see that
module's docstring for the reasoning. What's specific to *this* hook is
entirely about the trigger:
recognising an approved `ExitPlanMode` call and getting the body out of
it, which only exists as a tool call on Claude Code. Codex has no
`ExitPlanMode` equivalent (see docs/codex-hook-surface.md), so its own
hook reacts to the agent writing the plan file directly instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import _common
import plan_header
from plan_header import _done_line, _parent_path, _scope_patterns, _verify_override
from plan_header import missing_required_sections as _missing_required_sections

__all__ = [  # re-exported for existing white-box tests, not used within this module
    "_done_line",
    "_missing_required_sections",
    "_parent_path",
    "_scope_patterns",
    "_verify_override",
]

_APPROVED_MARKER = "## Approved Plan:"
_SAVED_PATH_PATTERN = re.compile(r"Your plan has been saved to:\s*(\S+)")


def _saved_plan_path(tool_response: str) -> Path | None:
    match = _SAVED_PATH_PATTERN.search(tool_response)
    return Path(match.group(1)) if match else None


def _embedded_plan_body(tool_response: str) -> str | None:
    index = tool_response.find(_APPROVED_MARKER)
    if index == -1:
        return None
    return tool_response[index + len(_APPROVED_MARKER) :].strip("\n")


def _plan_body(tool_response: str) -> str | None:
    """The approved plan's markdown, or None if this wasn't an approval.

    Prefers reading the file the developer actually approved on screen;
    falls back to the copy embedded in `tool_response` if that path is
    missing or unreadable.
    """
    embedded = _embedded_plan_body(tool_response)
    if embedded is None:
        return None
    saved_path = _saved_plan_path(tool_response)
    if saved_path is not None:
        try:
            return saved_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return embedded


def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        return
    if payload.get("tool_name") not in (None, "ExitPlanMode"):
        return
    tool_response = payload.get("tool_response")
    if not isinstance(tool_response, str):
        return
    body = _plan_body(tool_response)
    if body is None:
        return

    root = _common.repo_root(payload)

    if plan_header.is_feature_plan_body(body):
        plan_path = plan_header.feature_plan_path(root, plan_header.feature_slug(body))
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            plan_header.format_feature_header() + "\n\n" + body.strip("\n") + "\n",
            encoding="utf-8",
        )
        return

    branch = _common.current_branch(root) or "HEAD"
    header, missing = plan_header.derive_branch_header(root, branch, body)

    # `branch_plan_path` itself redirects a "features/"-prefixed branch
    # away from `.canon/plans/features/` -- see plan_header.py's
    # docstring -- so this write can never collide with a feature plan.
    plan_path = plan_header.branch_plan_path(root, branch)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(header + "\n\n" + body.strip("\n") + "\n", encoding="utf-8")

    notices = []
    if plan_header.branch_plan_collides_with_feature_namespace(branch):
        notices.append(plan_header.branch_namespace_collision_message(branch))
    if missing:
        notices.append(
            plan_header.missing_sections_message(
                plan_header.branch_plan_relative(branch), missing
            )
        )
    if notices:
        _common.context("PostToolUse", " ".join(notices))


if __name__ == "__main__":
    _common.fail_open(main)()
