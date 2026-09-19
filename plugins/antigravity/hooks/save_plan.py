# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PostToolUse:write_to_file` hook -- plan persistence (Antigravity port).

In Antigravity, plans are authored directly via `write_to_file` into
`.canon/plans/<branch>.md` (or `.canon/plans/features/<slug>.md` for feature plans).

This hook:
1. Inspects `TargetFile`. If the file is outside `.canon/plans/`, or not markdown,
   emits `{}` immediately and does nothing.
2. If within `.canon/plans/`, reads the written content, parses frontmatter and body,
   derives canonical frontmatter:
   - For feature plans (`## Steps` section non-empty or in `features/` directory):
     `status: approved` and `steps:`.
   - For branch plans:
     `status: approved`, `base:`, `scope:`, `done:`, `verify:`, `parent:`, `notes:`.
3. Rewrites the file with derived frontmatter back to disk if modified.
4. Emits `{}` to satisfy Antigravity's PostToolUse contract.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_hooks_dir = str(Path(__file__).resolve().parent)
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

import _common_agy as _common  # noqa: E402
import plan_header  # noqa: E402

_PLANS_DIR_RELATIVE = ".canon/plans"
_FEATURE_PLANS_DIR_RELATIVE = ".canon/plans/features"
_APPROVED_MARKER = "## Approved Plan:"
_SAVED_PATH_PATTERN = re.compile(r"Your plan has been saved to:\s*(\S+)")
_REQUIRED_SECTION_LABELS = {
    "non-goals": "Non-goals",
    "verification": "Verification",
}

_H1_HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_SCOPE_SECTION_KEYS = ("scope", "in scope", "files")
_DONE_SECTION_KEYS = ("done", "definition of done", "done when")
_PARENT_SECTION_KEYS = ("parent", "parent plan", "feature")
_BULLET_PREFIX = re.compile(r"^[-*+]\s+")
_BACKTICKED = re.compile(r"`([^`]+)`")
_PATH_TOKEN = re.compile(r"^[A-Za-z0-9_./*?\[\]{}-]+$")
_MAX_SCOPE_PATTERNS = 40
_MAX_DONE_CHARS = 200
_VERIFICATION_SECTION_KEYS = ("verification",)
_LONE_BACKTICKED = re.compile(r"^`([^`]+)`$")
_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 60


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


def _slugify(text: str) -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", text.lower()).strip("-")
    return slug[:_MAX_SLUG_LENGTH].strip("-") or "feature"


def _feature_slug(body: str) -> str:
    match = _H1_HEADING_PATTERN.search(body)
    return _slugify(match.group(1)) if match else "feature"


def _section_text(sections: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = sections.get(key, "").strip()
        if value:
            return value
    return ""


def _clean_token(raw: str) -> str:
    token = _BULLET_PREFIX.sub("", raw.strip()).strip()
    return token.strip("`").strip().rstrip(",.;").strip()


def _scope_patterns(section: str) -> list[str]:
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
    for line in section.splitlines():
        token = _clean_token(line)
        if token:
            return " ".join(token.split())[:_MAX_DONE_CHARS]
    return None


def _verify_override(section: str) -> str | None:
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _LONE_BACKTICKED.match(stripped)
        return match.group(1).strip() or None if match else None
    return None


def _parent_path(root: Path, section: str) -> str | None:
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


def _format_feature_header() -> str:
    return "\n".join(["---", "status: approved", "steps:", "---"])


def _format_header(
    *,
    base: str | None,
    verify: str | None,
    scope: list[str],
    done: str | None,
    parent: str | None,
    notes: list[str],
) -> str:
    lines = [
        "---",
        "status: approved",
        _header_line("base", base),
        _header_line("scope", f"[{', '.join(scope)}]" if scope else None),
        _header_line("done", done),
        _header_line("verify", verify),
        _header_line("parent", parent),
    ]
    if notes:
        lines.append(_header_line("notes", "; ".join(notes)))
    lines.append("---")
    return "\n".join(lines)


def _handle_legacy_exit_plan_mode(payload: dict[str, Any], root: Path) -> None:
    tool_response = payload.get("tool_response")
    if not isinstance(tool_response, str):
        _common.pass_stop()
        return
    idx = tool_response.find(_APPROVED_MARKER)
    if idx == -1:
        _common.pass_stop()
        return
    body = tool_response[idx + len(_APPROVED_MARKER) :].strip("\n")
    if not body:
        _common.pass_stop()
        return

    sections = _common.plan_sections(body)
    if sections.get("steps", "").strip():
        plan_path = root / _FEATURE_PLANS_DIR_RELATIVE / f"{_feature_slug(body)}.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            _format_feature_header() + "\n\n" + body.strip("\n") + "\n",
            encoding="utf-8",
        )
        _common.pass_stop()
        return

    branch = _common.current_branch(root) or "HEAD"
    default_branch = _common.default_branch(root)
    base = _common.merge_base(root, default_branch)
    missing = _missing_required_sections(body)
    notes = [
        f"{_REQUIRED_SECTION_LABELS[name]} section is missing or empty"
        for name in missing
    ]
    header = _format_header(
        base=base,
        verify=_verify_override(_section_text(sections, _VERIFICATION_SECTION_KEYS)),
        scope=_scope_patterns(_section_text(sections, _SCOPE_SECTION_KEYS)),
        done=_done_line(_section_text(sections, _DONE_SECTION_KEYS)),
        parent=_parent_path(root, _section_text(sections, _PARENT_SECTION_KEYS)),
        notes=notes,
    )
    plan_path = plan_header.branch_plan_path(root, branch)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(header + "\n\n" + body.strip("\n") + "\n", encoding="utf-8")
    _common.pass_stop()


def _normalize_branch_file(
    root: Path, branch: str, file_path: Path, content: str
) -> None:
    header_dict, body = _common.plan_header_and_body(content)
    sections = _common.plan_sections(body)
    default_branch = _common.default_branch(root)
    base = _common.merge_base(root, default_branch) or header_dict.get("base")
    missing = _missing_required_sections(body)
    notes = [
        f"{_REQUIRED_SECTION_LABELS[name]} section is missing or empty"
        for name in missing
    ]

    header = _format_header(
        base=base,
        verify=_verify_override(_section_text(sections, _VERIFICATION_SECTION_KEYS))
        or header_dict.get("verify"),
        scope=_scope_patterns(_section_text(sections, _SCOPE_SECTION_KEYS)),
        done=_done_line(_section_text(sections, _DONE_SECTION_KEYS))
        or header_dict.get("done"),
        parent=_parent_path(root, _section_text(sections, _PARENT_SECTION_KEYS))
        or header_dict.get("parent"),
        notes=notes,
    )

    new_content = header + "\n\n" + body.strip("\n") + "\n"
    if new_content != content:
        file_path.write_text(new_content, encoding="utf-8")
        _common.log_decision(
            root, "save_plan.py", "saved", reason=f"Plan saved to {file_path}"
        )


@_common.fail_open(fallback_fn=_common.pass_stop)
def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        _common.pass_stop()
        return

    if payload.get("error"):
        _common.pass_stop()
        return

    if not _common.has_workspace(payload):
        _common.pass_stop()
        return

    root = _common.repo_root(payload)
    if not root.is_dir():
        _common.pass_stop()
        return

    # Legacy Claude ExitPlanMode fallback
    if _common.tool_name(payload) == "ExitPlanMode":
        _handle_legacy_exit_plan_mode(payload, root)
        return

    target_file = _common.tool_target_file(payload)
    if not target_file:
        _common.pass_stop()
        return

    p = Path(target_file)
    if not p.is_absolute():
        p = root / p

    plans_dir = (root / _PLANS_DIR_RELATIVE).resolve()
    try:
        rel = p.resolve().relative_to(plans_dir)
    except (ValueError, OSError):
        _common.pass_stop()
        return

    if not p.name.endswith(".md") or p.resolve() == plans_dir:
        _common.pass_stop()
        return

    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        _common.pass_stop()
        return

    header_dict, body = _common.plan_header_and_body(content)
    if not body.strip():
        _common.pass_stop()
        return

    sections = _common.plan_sections(body)
    has_steps = bool(sections.get("steps", "").strip())
    under_features = len(rel.parts) > 1 and rel.parts[0].casefold() == "features"

    if under_features:
        if has_steps:
            new_content = _format_feature_header() + "\n\n" + body.strip("\n") + "\n"
            if new_content != content:
                p.write_text(new_content, encoding="utf-8")
                _common.log_decision(
                    root, "save_plan.py", "saved", reason=f"Feature plan saved to {rel}"
                )
            _common.pass_stop()
            return

        # Candidate for colliding branch plan: e.g. .canon/plans/features/auth.md
        branch = "/".join(rel.parts)[:-3]
        curr_branch = _common.current_branch(root)
        if curr_branch and curr_branch.casefold() == branch.casefold():
            dest = plan_header.branch_plan_path(root, curr_branch)
            if dest != p:
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    p.replace(dest)
                    p = dest
                    _normalize_branch_file(root, curr_branch, p, content)
                    _common.log_decision(
                        root,
                        "save_plan.py",
                        "redirected",
                        reason=f"Branch plan redirected to {dest}",
                    )
                    _common.pass_stop()
                    return
                else:
                    _normalize_branch_file(root, curr_branch, p, content)
                    _common.pass_stop()
                    return
            else:
                _normalize_branch_file(root, curr_branch, p, content)
                _common.pass_stop()
                return
        else:
            new_content = _format_feature_header() + "\n\n" + body.strip("\n") + "\n"
            if new_content != content:
                p.write_text(new_content, encoding="utf-8")
                _common.log_decision(
                    root, "save_plan.py", "saved", reason=f"Feature plan saved to {rel}"
                )
            _common.pass_stop()
            return

    under_branches = len(rel.parts) > 1 and rel.parts[0].casefold() == "branches"
    if under_branches:
        branch = "/".join(rel.parts[1:])[:-3]
        _normalize_branch_file(root, branch, p, content)
        _common.pass_stop()
        return

    branch = "/".join(rel.parts)[:-3]
    _normalize_branch_file(root, branch, p, content)
    _common.pass_stop()


if __name__ == "__main__":
    main()
