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

A second path, added for feature plans (§06's "planning a feature, not
just a branch"): a non-empty `## Steps` section is the signal that this
approval is a `frame`-shaped feature plan rather than an ordinary branch
plan -- no other skill ever asks for one, and branch position can't be
used instead (plan mode is sometimes entered before branching even for
an ordinary change, so "on the default branch at approval time" isn't a
reliable signal). A feature plan has no branch to name it after, so it
saves to `.canon/plans/features/<slug>.md`, the slug derived from the
draft's own `# ` title -- and its header carries `steps:` instead of
`scope:`/`base:`/`done:`/`verify:`/`parent:`, left blank the same way
those are: the canonical steps list lives in the body's `## Steps`
section, read the same way `## Non-goals` already is, not re-parsed
into the header.
"""

from __future__ import annotations

import re
from pathlib import Path

import _common
import _config

_PLANS_DIR_RELATIVE = ".canon/plans"
_FEATURE_PLANS_DIR_RELATIVE = ".canon/plans/features"
_APPROVED_MARKER = "## Approved Plan:"
_SAVED_PATH_PATTERN = re.compile(r"Your plan has been saved to:\s*(\S+)")
_REQUIRED_SECTION_LABELS = {
    "non-goals": "Non-goals",
    "verification": "Verification",
}
_H1_HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
# Heading aliases: plan mode phrases these a few ways, and the point is to
# read back what it already wrote rather than impose one spelling.
_SCOPE_SECTION_KEYS = ("scope", "in scope", "files")
_DONE_SECTION_KEYS = ("done", "definition of done", "done when")
_PARENT_SECTION_KEYS = ("parent", "parent plan", "feature")
_BULLET_PREFIX = re.compile(r"^[-*+]\s+")
_BACKTICKED = re.compile(r"`([^`]+)`")
# A path or glob has no whitespace in it. This is what keeps prose out of
# `scope:` -- see `_scope_patterns`.
_PATH_TOKEN = re.compile(r"^[A-Za-z0-9_./*?\[\]{}-]+$")
_MAX_SCOPE_PATTERNS = 40
_MAX_DONE_CHARS = 200
_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 60


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


def _slugify(text: str) -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", text.lower()).strip("-")
    return slug[:_MAX_SLUG_LENGTH].strip("-") or "feature"


def _feature_slug(body: str) -> str:
    """A filename-safe slug derived from the draft's own `# ` title, or
    "feature" if none is present -- `frame` is expected to always
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
    every save. A token is accepted only if it could actually be a path
    -- no whitespace in it -- which is what keeps a prose line like
    "this touches the slug module" out of the header entirely. Where a
    line carries backticked spans those are taken as the candidates, so
    "- `src/slugs/**` -- the slug module" yields the pattern and drops
    the commentary.

    Nothing is inferred from git: at approval time the branch has no
    changes to infer from.
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

    if _common.plan_sections(body).get("steps", "").strip():
        plan_path = root / _FEATURE_PLANS_DIR_RELATIVE / f"{_feature_slug(body)}.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            _format_feature_header() + "\n\n" + body.strip("\n") + "\n",
            encoding="utf-8",
        )
        return

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

    sections = _common.plan_sections(body)
    header = _format_header(
        base=base,
        verify=verify,
        scope=_scope_patterns(_section_text(sections, _SCOPE_SECTION_KEYS)),
        done=_done_line(_section_text(sections, _DONE_SECTION_KEYS)),
        parent=_parent_path(root, _section_text(sections, _PARENT_SECTION_KEYS)),
        notes=notes,
    )
    # `branch` may contain "/" (e.g. "feature/widget"), so the plan's own
    # parent directory -- not just .canon/plans/ itself -- needs creating.
    plan_path = root / _PLANS_DIR_RELATIVE / f"{branch}.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(header + "\n\n" + body.strip("\n") + "\n", encoding="utf-8")


if __name__ == "__main__":
    _common.fail_open(main)()
