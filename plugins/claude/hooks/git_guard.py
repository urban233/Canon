# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PreToolUse` hook for a shell command -- the destructive-git
guard and commit-trailer stripper.

Two independent jobs, per docs/plan.md §07's "Destructive git run
casually" spine-table row and §12's authorship section:

1. A short, fixed list of destructive operations -- the five §07 names
   (force push, hard reset, forced clean, branch deletion, merge) plus
   four `gh pr` operations -- are denied outright, always, with no
   exception and no `ask`: these are the operations §12's table marks
   "never" for Canon regardless of interaction mode. `rebase` onto a
   shared branch and `tag` deletion are in §12's broader table too, but
   both need a "is this actually shared" judgement this hook doesn't
   make, so they're left out rather than guessed at.

   §12's table calls merging or closing a pull request "the only real
   gate in the whole system," and separately says posting an
   *approving* review is never Canon's -- but until now that lived only
   as prose in the ship skill, which §07 explicitly says the spine must
   not depend on the model remembering. `gh pr merge` (any flags --
   `--squash`, `--rebase`, `--admin`, `--auto` all still open with the
   literal words `pr merge`) and `gh pr close` are denied outright.
   `gh pr review --approve` (and its short form `-a`, confirmed against
   `gh pr review --help` rather than guessed) is denied the same way.
   A bare `gh pr review` -- no `--approve`, `--comment`/`-c`, or
   `--request-changes`/`-r` -- is denied too: unlike the git patterns
   above, this one is a deliberate false-positive risk rather than a
   loose regex accident. `gh pr review` with no verdict flag is
   `gh`'s own interactive path to any of the three verdicts, including
   approval, and a command that reaches for that path has no legitimate
   non-interactive use Canon needs to allow -- an automated caller
   always has a verdict in mind and can name it. `gh pr review
   --comment` and `--request-changes` (and their short forms `-c`/
   `-r`) are the read-and-reply loop §12 says Canon needs, and are left
   untouched.

   Each pattern is written to match the destructive operation and
   nothing adjacent to it. That cuts both ways: a false negative here
   lets through something 12 says never to run, but a false positive
   is a `deny` with no `ask` and no override, against a command the
   developer had every right to run -- and the two commands most easily
   caught by a loose pattern, `git merge-base` and a `HEAD:refs/...`
   refspec, are both read-only or routine. `gh pr create`, `gh pr
   view/list/diff/checkout/status/comment`, and every `gh issue ...`
   command are the equivalent near-misses for the new patterns -- none
   of them contain the literal `pr merge`, `pr close`, or an
   unaccompanied `pr review`. The tests name every near-miss explicitly
   for that reason.
2. `git commit` commands carrying a `Co-Authored-By:` trailer have it
   stripped via `updatedInput` before the commit runs -- the mechanised
   half of §12's authorship guidance ("the git guard, which is already
   inspecting `git commit`, strips any AI-attribution trailer it
   finds"). Scoped to `git commit` only: a `gh pr create --body` is a
   separate surface, and §12 explicitly leaves that to documentation
   rather than mechanising it here.

Like `plan_gate.py`, this hook only ever denies, never asks -- see that
module's docstring for why.

Inert without a verification signal (docs/plan.md §07, "No signal, no
Canon"): with no `verify` command in `.canon/config.json` this hook is a
silent no-op. See docs/decisions/0001-what-inert-means.md for why
`stop.py` and `session_start.py` are the two exceptions.

The shell-command tool is named `Bash` on both platforms Canon ships for
(confirmed directly, not just documented from Claude Code's side) --
this hook needs no per-platform tool-name handling as a result.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import _common
import _config

_SHELL_TOOL_NAMES = ("Bash",)

_NON_DELIMITER = r"[^|;&]*"
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
            rf"\bgit\s+clean\b{_NON_DELIMITER}-\w*f\w*d\w*"
            rf"|\bgit\s+clean\b{_NON_DELIMITER}-\w*d\w*f\w*"
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
        # No flag check needed: every accepted form (`--squash`,
        # `--rebase`, `--merge`, `--admin`, `--auto`, or none at all)
        # still contains the literal `pr merge`.
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
        # The bare form: no `--approve`/`-a`, `--comment`/`-c`, or
        # `--request-changes`/`-r` anywhere in this segment. This is
        # `gh`'s own interactive path to any of the three verdicts --
        # see the module docstring for why an automated caller is
        # expected to always name one instead.
        re.compile(
            rf"\bgh\s+pr\s+review\b"
            rf"(?!{_NON_DELIMITER}(--approve\b|-a\b|--comment\b|-c\b"
            rf"|--request-changes\b|-r\b))"
        ),
        "an unflagged pull request review (it could end up approving)",
    ),
]

_COMMIT_PATTERN = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)
_TRAILER_LINE = re.compile(r"^[ \t]*Co-Authored-By:.*\n?", re.IGNORECASE | re.MULTILINE)


def _matched_destructive_operation(command: str) -> str | None:
    for pattern, label in _DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            return label
    return None


def _strip_attribution(command: str) -> str | None:
    """The command with every `Co-Authored-By:` trailer line removed, or
    None if there was nothing to strip."""
    stripped = _TRAILER_LINE.sub("", command)
    return stripped if stripped != command else None


def _allow_with_updated_command(tool_input: dict[str, Any], command: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {**tool_input, "command": command},
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        return
    if payload.get("tool_name") not in _SHELL_TOOL_NAMES:
        return
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return

    root = _common.repo_root(payload)
    if not _config.canon_is_active(_config.load_config(root)):
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
            assert isinstance(tool_input, dict)
            _allow_with_updated_command(tool_input, stripped)
            return


if __name__ == "__main__":
    _common.fail_open(main)()
