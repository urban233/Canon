# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PostToolUse` hook for an edit -- scope departure.

Compares the file(s) just touched against the current branch's saved plan
(`plan_header.branch_plan_path`): its header's `scope:` glob list, if
populated, and its `## Non-goals` section, if non-empty (see
docs/plan.md §07's "Scope creep" row). Neither is guaranteed to be
populated -- a freshly saved plan always writes `scope:` blank by design
(see `plan_header.py`'s docstring), meant to be filled in later by a human
or the `plan` skill's own dialogue -- so this hook has nothing to compare
against for a plan that hasn't had that done, and does nothing in that
case rather than manufacture a false departure.

The edit already happened by the time `PostToolUse` fires, so this hook
can never deny it -- only note it (first departure) or log it as a
decision (sustained departure), mirroring `stop.py`'s own
session-scoped consecutive-refusal counter for what "sustained" means.

Not implemented here: formatting the touched file (§07 also mentions
this for the same hook slot) -- hooks are stdlib-only and run via bare
`python3`, with no guaranteed access to a resolved formatter binary.
That separate decision has since been taken, and it went the other way:
`fast_check.py` runs a command the repository names and reports the
result rather than formatting anything. See
docs/decisions/0006-layer-one-reports-rather-than-formats.md.

Inert without a verification signal (docs/plan.md §07, "No signal, no
Canon"): with no `verify` command in `.canon/config.json` this hook is a
silent no-op. See docs/decisions/0001-what-inert-means.md for why
`stop.py` and `session_start.py` are the two exceptions.

**Touched-path extraction is deliberately defensive** -- see
`_common.edited_paths` -- and treats every path it finds as touched by the
same call. A call this can't extract any path from is a no-op, the same
fail-open posture as everywhere else in this module.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import _common
import _config
import plan_header

_COUNTER_NAME = "consecutive_scope_departures"
_SUSTAINED_THRESHOLD = 3

_EDIT_TOOL_NAMES = (None, *_common.EDIT_TOOL_NAMES)


def _match_parts(pattern_parts: list[str], path_parts: list[str]) -> bool:
    if not pattern_parts:
        return not path_parts
    head = pattern_parts[0]
    rest = pattern_parts[1:]
    if head == "**":
        if not rest:
            return True
        return any(
            _match_parts(rest, path_parts[i:]) for i in range(len(path_parts) + 1)
        )
    if not path_parts:
        return False
    if not fnmatch.fnmatchcase(path_parts[0], head):
        return False
    return _match_parts(rest, path_parts[1:])


def _glob_match(pattern: str, path: str) -> bool:
    """A small, hand-rolled `**`-aware glob matcher.

    Not `pathlib.Path.full_match`/`glob.translate` -- both Python
    3.13+, and hooks are held to a 3.9 floor (see pyproject.toml).
    `**` consumes zero or more whole path segments; each remaining
    segment is matched with `fnmatch`.
    """
    return _match_parts(pattern.split("/"), path.split("/"))


def _parse_scope_patterns(raw: str) -> list[str]:
    """Split a `scope:` value (e.g. `[src/slugs/**, tests/slugs/**]`,
    per docs/plan.md §06's example) into individual glob patterns."""
    stripped = raw.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1]
    return [part.strip() for part in stripped.split(",") if part.strip()]


def _relative_path(root: Path, file_path: str) -> str | None:
    try:
        return str(Path(file_path).resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return None


def _mentioned_in_non_goals(non_goals: str, relative_path: str) -> bool:
    if not non_goals.strip():
        return False
    haystack = non_goals.lower()
    if relative_path.lower() in haystack:
        return True
    filename = Path(relative_path).name.lower()
    return bool(filename) and filename in haystack


def _read_counter(counter_dir: Path | None) -> int:
    if counter_dir is None:
        return 0
    try:
        text = (counter_dir / _COUNTER_NAME).read_text(encoding="utf-8")
        return int(text.strip())
    except (OSError, ValueError):
        return 0


def _write_counter(counter_dir: Path | None, count: int) -> None:
    if counter_dir is None:
        return
    try:
        counter_dir.mkdir(parents=True, exist_ok=True)
        (counter_dir / _COUNTER_NAME).write_text(str(count), encoding="utf-8")
    except OSError:
        pass


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
    if not _config.canon_is_active(_config.load_config(root)):
        return  # no verification signal: Canon is inert, not checking scope
    relative_paths = [
        relative for path in touched if (relative := _relative_path(root, path))
    ]
    if not relative_paths:
        return

    branch = _common.current_branch(root) or "HEAD"
    plan_path = plan_header.branch_plan_path(root, branch)
    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError:
        return

    header, body = _common.plan_header_and_body(text)
    scope_raw = header.get("scope", "")
    patterns: list[str] = _parse_scope_patterns(scope_raw) if scope_raw else []
    non_goals = _common.plan_sections(body).get("non-goals", "")

    if not patterns and not non_goals.strip():
        return  # nothing declared to compare against

    departed_paths: list[str] = []
    departure_reasons: dict[str, list[str]] = {}
    for relative_path in relative_paths:
        out_of_scope = bool(patterns) and not any(
            _glob_match(pattern, relative_path) for pattern in patterns
        )
        named_in_non_goals = _mentioned_in_non_goals(non_goals, relative_path)
        if not (out_of_scope or named_in_non_goals):
            continue
        reasons = []
        if out_of_scope:
            reasons.append(f"outside the plan's declared scope ({scope_raw.strip()})")
        if named_in_non_goals:
            reasons.append("named in the plan's ## Non-goals")
        departed_paths.append(relative_path)
        departure_reasons[relative_path] = reasons

    counter_dir = _common.state_dir(payload)
    if not departed_paths:
        _write_counter(counter_dir, 0)
        return

    count = _read_counter(counter_dir) + 1
    _write_counter(counter_dir, count)

    reason = "; ".join(
        f"{path} is " + " and ".join(reasons)
        for path, reasons in departure_reasons.items()
    )

    if count >= _SUSTAINED_THRESHOLD:
        _common.log_decision(root, "check_scope.py", "departure", reason=reason)
        message = (
            f"Sustained scope departure ({count} consecutive edits): {reason}. "
            "Consider revising the plan's scope, or stopping to reconsider "
            "whether this work belongs on this branch."
        )
    else:
        message = f"Possible scope departure: {reason}."

    _common.context("PostToolUse", message)


if __name__ == "__main__":
    _common.fail_open(main)()
