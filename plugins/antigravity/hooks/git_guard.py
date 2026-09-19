# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PreToolUse:run_command` hook -- the destructive-git guard and
commit-trailer stripper (Antigravity port).

Two independent jobs, per docs/plan.md §07's "Destructive git run casually"
spine-table row and §12's authorship section:

1. A short, fixed list of destructive git operations -- exactly the five
   §07 names (force push, hard reset, forced clean, branch deletion, merge) --
   are denied outright, always, with no exception and no `ask`: these are the
   operations §12's table marks "never" for Canon regardless of interaction mode.

   Each pattern is written to match the destructive operation and nothing adjacent
   to it (e.g. `git merge-base` and `git push origin HEAD:refs/heads/x` are allowed).

2. `git commit` commands carrying a `Co-Authored-By:` trailer have it stripped
   via Antigravity's `overwrite: {"CommandLine": stripped}` payload before the
   commit runs.

Inert without a verification signal: with no `verify` command in `.canon/config.json`
this hook is a silent allow.
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
import _config  # noqa: E402

_NON_DELIMITER = r"(?:\\\n|[^|;&\n])*"
_DESTRUCTIVE_PATTERNS = [
    (
        re.compile(rf"\bgit\s+push\b{_NON_DELIMITER}(--force\b|-f\b)"),
        "a force push",
    ),
    (
        re.compile(rf"\bgit\s+reset\b{_NON_DELIMITER}--hard\b"),
        "a hard reset",
    ),
    (
        re.compile(
            rf"\bgit\s+clean\b{_NON_DELIMITER}(?:"
            rf"-\w*f\w*d\w*|-\w*d\w*f\w*"
            rf"|(?={_NON_DELIMITER}(?:-f\b|--force\b))(?={_NON_DELIMITER}(?:-d\b|--directory\b))"
            rf")"
        ),
        "a forced clean of untracked files/directories",
    ),
    (
        re.compile(rf"\bgit\s+branch\b{_NON_DELIMITER}(-D\b|--delete\b)"),
        "a branch deletion",
    ),
    (
        # `\s:\S` -- a refspec whose *source* side is empty (`git push
        # origin :old`) is the deletion form. A colon in the middle of a
        # refspec (`git push origin HEAD:refs/heads/x`) is an ordinary
        # push and must not match.
        re.compile(rf"\bgit\s+push\b{_NON_DELIMITER}(--delete\b|\s:\S)"),
        "a remote branch deletion",
    ),
    (
        # `(?![-\w])` keeps the read-only `git merge-base` and
        # `git merge-file` out of this; the second lookahead keeps the
        # recovery forms out. Aborting a merge is how you get *out* of
        # one, not the operation 12 marks "never".
        re.compile(
            rf"\bgit\s+merge(?![-\w])"
            rf"(?!{_NON_DELIMITER}--(abort|quit|continue)\b)"
        ),
        "a merge",
    ),
    (
        re.compile(r"\bgh\s+pr\s+merge\b"),
        "a pull request merge",
    ),
    (
        re.compile(r"\bgh\s+pr\s+close\b"),
        "a pull request close",
    ),
    (
        re.compile(rf"\bgh\s+pr\s+review\b{_NON_DELIMITER}(--approve\b|-a\b)"),
        "an approving pull request review",
    ),
    (
        re.compile(
            rf"\bgh\s+pr\s+review\b"
            rf"(?!{_NON_DELIMITER}(--approve\b|-a\b|--comment\b|-c\b"
            rf"|--request-changes\b|-r\b|--help\b|-h\b))"
        ),
        "a pull request review with no verdict flag "
        "(name --comment or --request-changes instead)",
    ),
]

_COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)
_TRAILER_LINE = re.compile(r"^[ \t]*Co-Authored-By:.*\n?", re.IGNORECASE | re.MULTILINE)
_QUOTE_CHAR = re.compile(r"[\"']")

_QUOTED_SPAN = re.compile(r"'[^']*'|\"[^\"]*\"")


def _blank_quoted_spans(command: str) -> str:
    """`command` with every single- or double-quoted span *that
    contains whitespace* replaced by spaces of the same length."""

    def _blank(match: re.Match[str]) -> str:
        span = match.group()
        return " " * len(span) if re.search(r"\s", span[1:-1]) else span

    return _QUOTED_SPAN.sub(_blank, command)


_RECOGNIZED_COMMAND_TOOLS = {
    "run_command",
    "Bash",
}


def _matched_destructive_operation(command: str) -> str | None:
    sanitized = _blank_quoted_spans(command)
    for pattern, label in _DESTRUCTIVE_PATTERNS:
        if pattern.search(sanitized):
            return label
    return None


def _strip_attribution(command: str) -> str | None:
    """The command with every `Co-Authored-By:` trailer line removed, or
    None if there was nothing to strip."""

    def _rewrite(match: re.Match[str]) -> str:
        line = match.group()
        quotes = "".join(_QUOTE_CHAR.findall(line))
        return quotes + "\n" if quotes and line.endswith("\n") else quotes

    stripped = _TRAILER_LINE.sub(_rewrite, command)
    return stripped if stripped != command else None


@_common.fail_open(fallback_fn=_common.allow)
def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        _common.allow()
        return

    tool_name = _common.tool_name(payload)
    if not tool_name or tool_name not in _RECOGNIZED_COMMAND_TOOLS:
        _common.allow()
        return

    command = _common.tool_command(payload)
    if not command:
        _common.allow()
        return

    if not _common.has_workspace(payload):
        _common.allow()
        return

    root = _common.repo_root(payload)
    if not root.is_dir():
        _common.allow()
        return

    if not _config.canon_is_active(_config.load_config(root)):
        _common.allow()
        return  # no verification signal: Canon is inert, not guarding

    label = _matched_destructive_operation(command)
    if label is not None:
        reason = (
            f"Canon never runs {label} -- if you genuinely want this, run it yourself."
        )
        _common.log_decision(root, "git_guard.py", "deny", reason=reason)
        _common.deny(reason)
        return

    if _COMMIT_PATTERN.search(command):
        stripped = _strip_attribution(command)
        if stripped is not None:
            _common.log_decision(
                root,
                "git_guard.py",
                "stripped_attribution",
                reason="removed a Co-Authored-By trailer from a git commit",
            )
            overwrite: dict[str, Any] = {"CommandLine": stripped}
            raw_args = _common.tool_args(payload)
            if "command" in raw_args:
                overwrite["command"] = stripped
            _common.allow(overwrite=overwrite)
            return

    _common.allow()


if __name__ == "__main__":
    main()
