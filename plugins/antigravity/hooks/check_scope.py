# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PostToolUse:replace_file_content|write_to_file` hook --
scope departure (Antigravity port).

Compares the file just touched against the current branch's saved plan
(`.canon/plans/<branch>.md`): its header's `scope:` glob list, if
populated, and its `## Non-goals` section, if non-empty (see
docs/plan.md §07's "Scope creep" row).

Under Antigravity's lifecycle protocol, PostToolUse hooks strictly emit `{}`
(empty object) to allow tool execution recording to complete.

This hook:
1. Tracks consecutive departures under
   `artifactDirectoryPath / conversationId / canon / consecutive_scope_departures`.
2. Records the last departure reason into `last_scope_departure` for session awareness.
3. When consecutive departures reach threshold (>= 3), logs a `departure` decision
   to `.canon/hooks/decisions.jsonl`.
4. Exempts edits to Canon internal metadata (`.canon/`).
5. Inert without a verification signal (`_config.canon_is_active`).
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

_hooks_dir = str(Path(__file__).resolve().parent)
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

import _common_agy as _common  # noqa: E402
import _config  # noqa: E402
import plan_header  # noqa: E402

_PLANS_DIR_RELATIVE = ".canon/plans"
_COUNTER_NAME = "consecutive_scope_departures"
_LAST_DEPARTURE_NAME = "last_scope_departure"
_SUSTAINED_THRESHOLD = 3

_RECOGNIZED_EDIT_TOOLS = {
    "replace_file_content",
    "write_to_file",
    "Edit",
    "Write",
}


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
    """A small, hand-rolled `**`-aware glob matcher."""
    return _match_parts(pattern.split("/"), path.split("/"))


def _parse_scope_patterns(raw: str) -> list[str]:
    """Split a `scope:` value (e.g. `[src/slugs/**, tests/slugs/**]`) into patterns."""
    stripped = raw.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1]
    return [part.strip() for part in stripped.split(",") if part.strip()]


def _relative_path(root: Path, file_path: str) -> str | None:
    try:
        p = Path(file_path)
        if not p.is_absolute():
            p = root / p
        return p.resolve().relative_to(root.resolve()).as_posix()
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


def _write_last_departure(counter_dir: Path | None, reason: str) -> None:
    if counter_dir is None:
        return
    try:
        counter_dir.mkdir(parents=True, exist_ok=True)
        (counter_dir / _LAST_DEPARTURE_NAME).write_text(reason, encoding="utf-8")
    except OSError:
        pass


def _clear_last_departure(counter_dir: Path | None) -> None:
    if counter_dir is None:
        return
    try:
        p = counter_dir / _LAST_DEPARTURE_NAME
        if p.exists():
            p.unlink()
    except OSError:
        pass


@_common.fail_open(fallback_fn=_common.pass_stop)
def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        _common.pass_stop()
        return

    # If the tool call produced an error, do not perform scope checks
    if payload.get("error"):
        _common.pass_stop()
        return

    tool_name = _common.tool_name(payload)
    if tool_name and tool_name not in _RECOGNIZED_EDIT_TOOLS:
        _common.pass_stop()
        return

    target_file = _common.tool_target_file(payload)
    if not target_file:
        _common.pass_stop()
        return

    if not _common.has_workspace(payload):
        _common.pass_stop()
        return

    root = _common.repo_root(payload)
    if not root.is_dir():
        _common.pass_stop()
        return

    if not _config.canon_is_active(_config.load_config(root)):
        _common.pass_stop()
        return  # no verification signal: Canon is inert, not checking scope

    relative_path = _relative_path(root, target_file)
    if relative_path is None:
        _common.pass_stop()
        return

    # Exempt Canon internal metadata
    if relative_path.startswith(".canon/") or relative_path == ".canon":
        _common.pass_stop()
        return

    branch = _common.current_branch(root) or "HEAD"
    plan_path = plan_header.branch_plan_path(root, branch)
    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError:
        _common.pass_stop()
        return

    header, body = _common.plan_header_and_body(text)
    scope_raw = header.get("scope", "")
    patterns: list[str] = _parse_scope_patterns(scope_raw) if scope_raw else []
    non_goals = _common.plan_sections(body).get("non-goals", "")

    if not patterns and not non_goals.strip():
        _common.pass_stop()
        return  # nothing declared to compare against

    out_of_scope = bool(patterns) and not any(
        _glob_match(pattern, relative_path) for pattern in patterns
    )
    named_in_non_goals = _mentioned_in_non_goals(non_goals, relative_path)
    departed = out_of_scope or named_in_non_goals

    counter_dir = _common.state_dir(payload)
    if not departed:
        _write_counter(counter_dir, 0)
        _clear_last_departure(counter_dir)
        _common.pass_stop()
        return

    count = _read_counter(counter_dir) + 1
    _write_counter(counter_dir, count)

    reasons = []
    if out_of_scope:
        reasons.append(f"outside the plan's declared scope ({scope_raw.strip()})")
    if named_in_non_goals:
        reasons.append("named in the plan's ## Non-goals")
    reason = f"{relative_path} is " + " and ".join(reasons)
    _write_last_departure(counter_dir, reason)

    if count >= _SUSTAINED_THRESHOLD:
        _common.log_decision(
            root,
            "check_scope.py",
            "departure",
            reason=reason,
            extra={"consecutive": count, "file": relative_path},
        )

    _common.pass_stop()


if __name__ == "__main__":
    main()
