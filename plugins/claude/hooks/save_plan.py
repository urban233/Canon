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

The header fills in only what's genuinely derivable (`status`, `base`,
`verify`) and leaves the rest blank rather than inventing it -- per
docs/plan.md §06's own rule. This hook never runs `git add` or
`git commit`: per §12, the saved plan rides inside whatever commit the
developer's own work produces.
"""

from __future__ import annotations

import re
from pathlib import Path

import _common
import _config

_PLANS_DIR_RELATIVE = ".canon/plans"
_APPROVED_MARKER = "## Approved Plan:"
_SAVED_PATH_PATTERN = re.compile(r"Your plan has been saved to:\s*(\S+)")
_REQUIRED_SECTION_LABELS = {
    "non-goals": "Non-goals",
    "verification": "Verification",
}


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


def _missing_required_sections(body: str) -> list[str]:
    sections = _common.plan_sections(body)
    return [name for name in _REQUIRED_SECTION_LABELS if not sections.get(name)]


def _yaml_scalar(value: str | None) -> str:
    if not value:
        return ""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _header_line(key: str, value: str | None) -> str:
    scalar = _yaml_scalar(value)
    return f"{key}: {scalar}" if scalar else f"{key}:"


def _format_header(*, base: str | None, verify: str | None, notes: list[str]) -> str:
    lines = [
        "---",
        "status: approved",
        _header_line("base", base),
        "scope:",
        "done:",
        _header_line("verify", verify),
        "parent:",
    ]
    if notes:
        lines.append(_header_line("notes", "; ".join(notes)))
    lines.append("---")
    return "\n".join(lines)


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
    branch = _common.current_branch(root) or "HEAD"
    default_branch = _common.default_branch(root)
    base = _common.merge_base(root, default_branch)

    config = _config.load_config(root)
    verify = None
    if config is not None and _config.has_verification_signal(config):
        verify_value = config.get("verify")
        if isinstance(verify_value, str):
            verify = verify_value

    notes = [
        f"{_REQUIRED_SECTION_LABELS[name]} section is missing or empty"
        for name in _missing_required_sections(body)
    ]

    header = _format_header(base=base, verify=verify, notes=notes)
    # `branch` may contain "/" (e.g. "feature/widget"), so the plan's own
    # parent directory -- not just .canon/plans/ itself -- needs creating.
    plan_path = root / _PLANS_DIR_RELATIVE / f"{branch}.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(header + "\n\n" + body.strip("\n") + "\n", encoding="utf-8")


if __name__ == "__main__":
    _common.fail_open(main)()
