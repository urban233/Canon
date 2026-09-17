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
   `gh pr review --help` rather than guessed) is denied the same way,
   and so is a bare `gh pr review` naming none of `--approve`,
   `--comment`/`-c`, or `--request-changes`/`-r` -- see that pattern's
   own comment below for why the bare form earns a deny rather than a
   pass-through. `gh pr review --comment` and `--request-changes` (and
   their short forms) are the read-and-reply loop §12 says Canon needs,
   and stay untouched, as does the read-only `gh pr review --help`.

   Matching runs against the command with every quoted span *that
   contains whitespace* blanked to spaces first (`_blank_quoted_spans`),
   not the raw text -- without that, `git commit -m "fix: deny gh pr
   merge/close in the git guard"` would deny itself, and `gh pr review
   42 --request-changes -b "document the -a flag"` would deny the very
   correction-loop reply §12 asks for. Whitespace inside the quotes is
   what marks prose rather than a token: a quoted flag with none, like
   `'-D'` or `"--force"`, is exactly what the shell hands the program
   once it strips the quotes, so it still matches -- `git branch '-D'
   feature/x` is a branch deletion whether or not the `-D` was quoted.
   The guard inspects the command, not its prose arguments, and that
   whitespace test is how it tells the two apart. This is a tripwire
   against casual action, not a sandbox, and it accepts one deliberate
   false negative in exchange: a destructive invocation that sits
   entirely inside one multi-word quoted string, such as `bash -c "gh
   pr merge 42"`, is indistinguishable from prose by this rule and
   passes. An agent determined to evade a regex always can; closing
   that particular gap is not this hook's job, and doing so would cost
   every legitimate quoted mention of a forbidden verb. Blanking feeds
   only the destructive-pattern check -- the `git commit` detection
   just below and the trailer stripper both read the original,
   unblanked command, so `bash -c "git commit -m '...'"` still has its
   `Co-Authored-By:` trailer found and stripped.

   Each pattern is written to match the destructive operation and
   nothing adjacent to it. That cuts both ways: a false negative here
   lets through something 12 says never to run, but a false positive
   is a `deny` with no `ask` and no override, against a command the
   developer had every right to run -- and the two commands most easily
   caught by a loose pattern, `git merge-base` and a `HEAD:refs/...`
   refspec, are both read-only or routine. `gh pr create`, `gh pr
   view/list/diff/checkout/status/comment`, and every `gh issue ...`
   command are the equivalent near-misses for the new patterns -- once
   quoted prose is blanked, none of them contain the literal `pr
   merge`, `pr close`, or an unaccompanied `pr review`. The tests name
   every near-miss explicitly for that reason.
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

# A newline is a segment boundary, same as `|`/`;`/`&` -- a flag on one
# line of a multi-line command must not excuse an unrelated command on
# another. `\\\n` is the one exception: a backslash-newline is an
# ordinary shell line continuation, not a boundary, and this repo's own
# multi-line `git commit` invocations are written that way.
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
        # The bare form: none of `--approve`/`-a`, `--comment`/`-c`,
        # `--request-changes`/`-r`, or `--help`/`-h` appear anywhere in
        # this segment. Unflagged, `gh pr review` is `gh`'s own
        # interactive path to any of the three verdicts, including
        # approval, and a non-interactive caller always has a verdict
        # in mind and can name it -- so there is no legitimate
        # non-interactive use this excludes. `--help`/`-h` is carved
        # out separately because it is the one bare-looking invocation
        # that verdicts nothing at all -- a read-only documentation
        # lookup, not a path to approval.
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
# `.*` deliberately still runs to the end of the line, exactly as it did
# before issue #58 -- `_strip_attribution` below is what changed to fix
# that issue, not this pattern. See its docstring for why matching the
# whole line and then filtering the match down to quote characters,
# rather than narrowing what this pattern matches in the first place,
# is the fix.
_TRAILER_LINE = re.compile(r"^[ \t]*Co-Authored-By:.*\n?", re.IGNORECASE | re.MULTILINE)
# Used by `_strip_attribution` to keep only the quote characters a
# matched trailer line contained, in order -- see that function's
# docstring.
_QUOTE_CHAR = re.compile(r"[\"']")

_QUOTED_SPAN = re.compile(r"'[^']*'|\"[^\"]*\"")


def _blank_quoted_spans(command: str) -> str:
    """`command` with every single- or double-quoted span *that
    contains whitespace* replaced by spaces of the same length.

    Whitespace inside the quotes is what actually distinguishes prose
    from a flag, not the quoting itself: a quoted span with no
    whitespace in it (`'-D'`, `"--force"`) is a single token the shell
    hands to the program with the quotes stripped, indistinguishable
    from the same flag written bare, so it must still match. A quoted
    span *with* whitespace in it (a commit message, a `--body`, a `-b`
    reply) is prose that isn't part of the command at all.

    Used only for destructive-pattern matching -- see the module
    docstring's first section for why prose inside quotes must not
    feed that check. Never used for detecting whether the command is a
    `git commit`, nor for `_strip_attribution`: both have to see the
    original text, and the trailer `_strip_attribution` looks for lives
    inside the very quote this would blank out.
    """

    def _blank(match: re.Match[str]) -> str:
        span = match.group()
        return " " * len(span) if re.search(r"\s", span[1:-1]) else span

    return _QUOTED_SPAN.sub(_blank, command)


def _matched_destructive_operation(command: str) -> str | None:
    for pattern, label in _DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            return label
    return None


def _strip_attribution(command: str) -> str | None:
    """The command with every `Co-Authored-By:` trailer line removed, or
    None if there was nothing to strip.

    Issue #58: `_TRAILER_LINE`'s `.*` runs to the end of the line, so a
    trailer that happens to be the last line inside a quoted `-m`
    message shares that line with the closing quote. Deleting the whole
    matched line outright -- this function's first fix -- deletes that
    quote along with it, handing back an unbalanced command through
    `updatedInput`. Narrowing the pattern to stop at any quote
    character fixes that, but trades it for a quieter defect: a trailer
    whose own text contains a `'` or a `"` (an ordinary thing for a
    human co-author's name to have, e.g. "Mary O'Neill", and this
    pattern matches any `Co-Authored-By:` trailer, not only Claude's)
    is then only partially removed, leaving a readable fragment of the
    trailer in the command while `log_decision` still reports a clean
    strip.

    The fix instead keeps the pattern matching the whole line, and
    rewrites each match to contain only the quote characters that line
    contained, in their original order, plus the line's own trailing
    newline if it had one and kept at least one quote character --
    dropping every other character, including the literal
    `Co-Authored-By:` label. Because characters outside the match are
    left untouched, and the characters kept inside it are exactly its
    quote-character subsequence in order, the sequence of `"` and `'`
    characters read across the *whole* command is identical before and
    after, not merely equal in count -- so no character can appear to
    cross from inside a quoted region to outside it, or vice versa, and
    no fragment of the trailer's own text can survive. This holds
    without this hook parsing the shell's quoting rules at all: a
    shell-aware rewrite would be the more thorough fix, but it turns a
    hook that runs before every `Bash` call into a shell parser, for a
    problem this line-local, quote-preserving rewrite mostly solves.

    Mostly, not entirely: quote-subsequence invariance is not sufficient
    for the command to still parse. A heredoc's terminator (`EOF` above)
    has to be alone on its line to close the heredoc, and that is a
    property of a line's *position*, not of quote characters -- no
    quote-preserving rewrite can see it. A trailer whose own text
    contains a quote character, immediately followed by a heredoc
    terminator line, used to glue a stray quote onto the front of that
    terminator (`'EOF` instead of `EOF`), which stops the terminator
    from matching and leaves the heredoc -- and the command -- unclosed.
    That is exactly the class of defect issue #58 is about, on the one
    form this repo's own commit style actually uses. Fixed by keeping
    the trailer line's own trailing newline in the replacement whenever
    a quote character survives, so a kept quote lands at the end of the
    line it came from rather than the start of the next one; a
    quote-free trailer still collapses to nothing, exactly as it did
    before this fix, so it can't leave a spurious blank line behind.

    A match always includes that literal `Co-Authored-By:` label, which
    contains no quote character, so every match is strictly longer than
    its replacement and this function can never rewrite a match back
    into the text it started as -- it never newly returns None.

    Known residual gap, found while fixing the terminator-gluing defect
    above and deliberately not chased further: macOS's system `/bin/
    bash` (3.2, still the default on an unmodified Mac) mis-lexes a
    `<<'quoted'` heredoc whenever its body contains an *odd* total count
    of `'` or of `"`, anywhere in the body, regardless of position --
    its single-pass lexer keeps tracking quote balance through what
    should be an opaque heredoc. A trailer with exactly one quote
    character (an ordinary apostrophe in a name) always leaves an odd
    count once the rest of the trailer's text is removed, so this fix's
    output, correct under both invariants above and confirmed against a
    modern bash (5.x), can still fail to parse under that one shell.
    Closing that gap without breaking the subsequence invariant would
    mean knowing which surviving quote characters are structurally
    load-bearing and which are incidental prose -- exactly the
    shell-parsing judgement this hook is built to avoid making. Left as
    a reported, not fixed, finding."""

    def _rewrite(match: re.Match[str]) -> str:
        line = match.group()
        quotes = "".join(_QUOTE_CHAR.findall(line))
        return quotes + "\n" if quotes and line.endswith("\n") else quotes

    stripped = _TRAILER_LINE.sub(_rewrite, command)
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

    # Quoted prose with whitespace in it (a commit message, a `gh pr
    # create --body`, a review reply) is not part of the command being
    # run and must not feed the destructive-pattern check below -- see
    # the module docstring for the cases this fixes and the false
    # negatives it deliberately still accepts. The `git commit` check
    # just below runs against the original `command`, not this: a
    # `bash -c "git commit ..."` must still be found and have its
    # trailer stripped.
    unquoted = _blank_quoted_spans(command)

    label = _matched_destructive_operation(unquoted)
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
