# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `PreToolUse` hook for a shell command -- the destructive-git
guard and commit-trailer stripper.

Two independent jobs, per docs/plan.md §07's "Destructive git run
casually" spine-table row and §12's authorship section:

1. A short, fixed list of destructive operations -- hard reset, forced
   clean, branch deletion, a plain force push, plus four `gh pr`
   operations -- are denied outright, always, with no exception and no
   `ask`: these are the operations §12's table marks "never" for Canon
   regardless of interaction mode. A `git merge`, a `git pull` of another
   branch, and a `--force-with-lease` push are judged by the branch they
   land on instead: denied onto the default branch, allowed on a feature
   branch, where they are how a branch -- a stacked one especially -- is
   kept up to date. See `_contextual_operation` and
   docs/decisions/0011-update-a-branch-never-merge-a-pull-request.md. `rebase` onto a
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

This hook only ever denies, never asks: an `ask` would put a "never"
operation one confirmation away.

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
from pathlib import Path
from typing import Any

import _common
import _config

_SHELL_TOOL_NAMES = ("Bash", "run_command")

# A newline is a segment boundary, same as `|`/`;`/`&` -- a flag on one
# line of a multi-line command must not excuse an unrelated command on
# another. `\\\n` is the one exception: a backslash-newline is an
# ordinary shell line continuation, not a boundary, and this repo's own
# multi-line `git commit` invocations are written that way.
_NON_DELIMITER = r"(?:\\\n|[^|;&\n])*"
_DESTRUCTIVE_PATTERNS = [
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
# whole line and then filtering the match down to its quote tokens,
# rather than narrowing what this pattern matches in the first place,
# is the fix.
_TRAILER_LINE = re.compile(r"^[ \t]*Co-Authored-By:.*\n?", re.IGNORECASE | re.MULTILINE)
# A quote character together with the whole run of backslashes directly
# in front of it. `_strip_attribution` keeps these tokens, in order, and
# drops everything else on a matched trailer line. The backslash run has
# to travel with its quote: it is what decides whether that quote toggles
# quoting at all, and the run's *length* is what decides it (issue #69).
# See that function's docstring.
_QUOTE_TOKEN = re.compile(r"\\*[\"']")

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


# --- Merges and force pushes: judged by the branch they land on --------
#
# A merge or a force push is only "never" when it lands on the default
# branch: that is a pull request merged the classical way, or shared
# history rewritten. On a feature branch the same commands are how a
# branch is kept up to date -- merging its base or its parent step in,
# fast-forwarding to its remote, or pushing a rebased stacked branch with
# `--force-with-lease` -- and denying them blocked exactly that work in
# the field (`git merge --ff-only origin/<branch>`, `git merge origin/main`
# into a PR branch, a `--force-with-lease` after a rebase). See
# docs/decisions/0011-update-a-branch-never-merge-a-pull-request.md.
#
# Each segment of a compound command is judged on its own, against the
# branch it would run on: the current branch, or the last
# `git checkout`/`git switch` earlier in the same command. A branch that
# can't be determined (detached HEAD, an unborn repository, a `cd`
# elsewhere) is not treated as the default branch -- a tripwire that
# guesses "main" would deny ordinary work on uncertainty.

_SEGMENT_SPLIT = re.compile(r"[|;&]|(?<!\\)\n")
_UPSTREAM_ALIASES = ("@{u}", "@{upstream}")
# `git merge` options that take a separate value, so the value is not
# mistaken for a branch to merge.
_MERGE_VALUE_OPTIONS = {
    "-m",
    "-F",
    "-s",
    "-X",
    "--message",
    "--file",
    "--strategy",
    "--strategy-option",
    "--into-name",
    "--cleanup",
}
_GIT_GLOBAL_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


# Grouping and substitution punctuation glued to a word -- `(git`,
# `$(git`, `` `git ``, `--force)` -- is not part of the word git sees.
_GLUED_PUNCTUATION = re.compile(r"^[$(`]+|[)`]+$")


def _tokens(segment: str) -> list[str]:
    return [
        _GLUED_PUNCTUATION.sub("", t).strip("'\"")
        for t in segment.replace("\\\n", " ").split()
    ]


def _is_git(token: str) -> bool:
    """`git` itself, or git run by path (`/usr/bin/git`)."""
    return token.rsplit("/", 1)[-1] == "git"


def _git_subcommand(
    tokens: list[str], root: Path | None = None
) -> tuple[str, list[str], bool] | None:
    """`(subcommand, its arguments, elsewhere)` for a segment that runs
    git, or None. `elsewhere` is True when a global option (`-C`,
    `--git-dir`, ...) points git at another repository, whose branches
    this hook can't see. A `-C` naming this repository's own root, by
    absolute path, is not elsewhere."""
    index = next((i for i, t in enumerate(tokens) if _is_git(t)), None)
    if index is None:
        return None
    elsewhere = False
    index += 1
    while index < len(tokens) and tokens[index].startswith("-"):
        option, _, value = tokens[index].partition("=")
        if option in _GIT_GLOBAL_VALUE_OPTIONS and not value:
            index += 1
            value = tokens[index] if index < len(tokens) else ""
        if option == "-C":
            elsewhere = elsewhere or not _is_repo_root(value, root)
        elif option in ("--git-dir", "--work-tree"):
            elsewhere = True
        index += 1
    if index >= len(tokens):
        return None
    return tokens[index], tokens[index + 1 :], elsewhere


def _is_repo_root(path: str, root: Path | None) -> bool:
    if root is None or not path.startswith("/"):
        return False
    try:
        return Path(path).resolve() == Path(root).resolve()
    except OSError:
        return False


def _checkout_target(args: list[str]) -> str | None:
    """The branch a `git checkout`/`git switch` leaves HEAD on, or None
    when it can't be read off the command (a path checkout, `-`, a
    detach)."""
    positional: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return None  # a path checkout: HEAD stays where it is
        if arg in ("-b", "-B", "-c", "-C", "--orphan"):
            return args[index + 1] if index + 1 < len(args) else None
        if arg in ("--detach", "-d", "-"):
            return None
        if not arg.startswith("-"):
            positional.append(arg)
        index += 1
    if not positional:
        return None
    if any(a in ("-t", "--track") or a.startswith("--track=") for a in args):
        # `--track origin/main` creates and switches to the local `main`.
        return positional[0].removeprefix("refs/remotes/").split("/", 1)[-1]
    return positional[0]


def _merge_sources(args: list[str]) -> list[str]:
    sources: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in _MERGE_VALUE_OPTIONS:
            index += 2
            continue
        if not arg.startswith("-"):
            sources.append(arg)
        index += 1
    return sources


def _merge_violation(args: list[str], branch: str | None, default: str) -> str | None:
    if any(a in ("--abort", "--quit", "--continue") for a in args):
        return None  # recovery: how you get out of a merge
    if branch != default:
        return None  # updating a feature branch
    sources = _merge_sources(args)
    syncing = (
        "--ff-only" in args
        and bool(sources)
        and all(
            source in (f"origin/{default}", *_UPSTREAM_ALIASES) for source in sources
        )
    )
    return None if syncing else "a merge into the default branch"


def _pull_violation(args: list[str], branch: str | None, default: str) -> str | None:
    """`git pull <remote> <other-branch>` on the default branch merges
    that branch into it -- a pull request merged locally. A plain
    `git pull`, or one naming the default branch itself, only updates."""
    if branch != default:
        return None
    positional = [a for a in args if not a.startswith("-")]
    refs = positional[1:]
    if any(ref.split(":", 1)[0].removeprefix("refs/heads/") != default for ref in refs):
        return "a merge into the default branch"
    return None


def _push_targets(positional: list[str], branch: str | None) -> list[str | None]:
    refspecs = positional[1:]
    if not refspecs:
        return [branch]
    targets: list[str | None] = []
    for refspec in refspecs:
        source, _, destination = refspec.lstrip("+").partition(":")
        target = destination or source
        target = target.removeprefix("refs/heads/")
        targets.append(branch if target == "HEAD" else target)
    return targets


def _push_violation(args: list[str], branch: str | None, default: str) -> str | None:
    positional = [a for a in args if not a.startswith("-")]
    short_flags = "".join(
        a[1:] for a in args if a.startswith("-") and not a.startswith("--")
    )
    long_flags = [a.split("=", 1)[0] for a in args if a.startswith("--")]
    if "--force" in long_flags or "f" in short_flags:
        return "a force push"
    if any(refspec.startswith("+") for refspec in positional[1:]):
        return "a force push"
    if "d" in short_flags:
        return "a remote branch deletion"
    leased = "--force-with-lease" in long_flags or "--force-if-includes" in long_flags
    if not leased:
        return None
    if "--all" in long_flags or "--mirror" in long_flags:
        return "a force push to every branch"
    if any(target == default for target in _push_targets(positional, branch)):
        return "a force push to the default branch"
    return None


def _contextual_operation(
    command: str,
    current_branch: str | None,
    default: str,
    root: Path | None = None,
) -> str | None:
    """The first merge or force push in `command` that lands on the
    default branch -- see the comment block above -- or None."""
    branch = current_branch
    for segment in _SEGMENT_SPLIT.split(command):
        tokens = _tokens(segment)
        if tokens and tokens[0] == "cd":
            branch = None
            continue
        parsed = _git_subcommand(tokens, root)
        if parsed is None:
            continue
        subcommand, args, elsewhere = parsed
        on = None if elsewhere else branch
        if subcommand in ("checkout", "switch") and not elsewhere:
            target = _checkout_target(args)
            if target is not None or "-" in args or "--detach" in args:
                branch = target
            continue
        judge = {
            "merge": _merge_violation,
            "pull": _pull_violation,
            "push": _push_violation,
        }.get(subcommand)
        if judge is not None:
            label = judge(args, on, default)
            if label is not None:
                return label
    return None


_CONTEXTUAL_PATTERN = re.compile(r"\bgit\b[^|;&\n]*\b(merge|pull|push)\b")


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
    rewrites each match to contain only its `_QUOTE_TOKEN` subsequence
    -- every quote character the line held, in order, each still
    carrying the run of backslashes that stood directly in front of it
    -- plus the line's own trailing newline if it had one and kept at
    least one token. Everything else goes, including the literal
    `Co-Authored-By:` label.

    What that preserves is quote *state*, not quote characters. Read
    the command as a sequence of quote characters, each tagged with the
    parity of the backslash run in front of it -- odd means escaped and
    inert, even means it toggles quoting -- and that tagged sequence is
    identical before and after the rewrite. So no quote can flip
    between inert and toggling, no character can appear to cross from
    inside a quoted region to outside it, and no fragment of the
    trailer's own text survives. All without the hook parsing the
    shell's quoting rules: a shell-aware rewrite would be more
    thorough, but it turns a hook that runs before every `Bash` call
    into a shell parser, for a problem this line-local rewrite mostly
    solves.

    Issue #69 is why the rule is about tokens and not characters. The
    first version kept the bare `"` and `'`, preserving the characters
    and destroying the parity: an escaped, inert quote was promoted
    into a real toggle. `'\\''` -- the standard way to get an apostrophe
    into a single-quoted message, so "Mary O'Neill" again -- collapsed
    to `'''`, and a lone `\\"` inside a double-quoted message to `"`.
    Both commands parsed before the rewrite and failed after it, under
    bash, zsh and sh alike.

    Mostly, not entirely: no invariant over quotes is sufficient for
    the command to still parse. A heredoc's terminator (`EOF` above)
    has to be alone on its line to close the heredoc, and that is a
    property of a line's *position*, not of quote characters -- no
    quote-preserving rewrite can see it. A trailer whose own text
    contains a quote character, immediately followed by a heredoc
    terminator line, used to glue a stray quote onto the front of that
    terminator (`'EOF` instead of `EOF`), which stops the terminator
    from matching and leaves the heredoc -- and the command -- unclosed,
    on the one form this repo's own commit style actually uses. Fixed
    by keeping the trailer line's own trailing newline whenever
    a token survives, so a kept quote lands at the end of the line it
    came from rather than the start of the next one; a quote-free
    trailer still collapses to nothing, so it can't leave a spurious
    blank line behind.

    A match always includes that literal `Co-Authored-By:` label, which
    holds no quote character and no backslash, so every match is
    strictly longer than its replacement and this function can never
    rewrite a match back into the text it started as -- it never newly
    returns None.

    Known residual gap, deliberately not chased: macOS's system
    `/bin/bash` (3.2, still the default on an unmodified Mac) mis-lexes
    a `<<'quoted'` heredoc whenever its body is not quote-*balanced*
    when read as ordinary shell text -- its single-pass lexer keeps
    tracking quote balance through what should be an opaque heredoc. A
    single apostrophe in a name is the common way to get there. Balance,
    not a count, is the rule: a body of `'"'` is odd-counted and parses
    fine, because the `"` nests inside the `'...'` pair, while `a'b"c`
    is even-counted and fails, because the `'` opens and never closes.

    This hook cannot cause that failure, and does not worsen it: bash
    3.2's verdict is a function of exactly the structure the invariant
    above preserves, so the verdict is the same before and after --
    measured, not argued, over 470 commands that parse before the
    rewrite, built by brute force from quotes and backslashes across
    five command shapes and each checked with `bash -n`, `zsh -n` and
    `sh -n`: none of them parsed before and failed after.

    That measurement replaces a narrower one that missed #69 entirely,
    and on its strength this note used to say the whole residual gap
    was bash-3.2-only, and so unreachable through Claude Code, whose
    `Bash` tool runs the user's `$SHELL`. It is scoped to the heredoc
    lexing above and always was; #69 broke zsh and sh too.

    Closing that gap anyway -- rewriting so the output parses under a
    shell the input already failed under -- would mean knowing which
    surviving quote characters are structurally load-bearing and which
    are incidental prose, exactly the shell-parsing judgement this hook
    is built to avoid making. Left as a reported, not fixed, finding."""

    def _rewrite(match: re.Match[str]) -> str:
        line = match.group()
        kept = "".join(_QUOTE_TOKEN.findall(line))
        return kept + "\n" if kept and line.endswith("\n") else kept

    stripped = _TRAILER_LINE.sub(_rewrite, command)
    return stripped if stripped != command else None


def _allow_with_updated_command(tool_input: dict[str, Any], command: str) -> None:
    """Let the call through, but with the rewritten command.

    Antigravity spells this `overwrite`, a shallow top-level merge into
    the tool call's own arguments, so it is keyed by that tool's real
    argument name (`CommandLine`) rather than by the snake_case view
    `read_payload` synthesizes. Claude Code and Codex take the whole
    input back under `updatedInput`.
    """
    if _common.host() == _common.HOST_ANTIGRAVITY:
        json.dump(
            {"decision": "allow", "overwrite": {"CommandLine": command}},
            sys.stdout,
        )
        sys.exit(0)
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
    if label is None and _CONTEXTUAL_PATTERN.search(unquoted):
        label = _contextual_operation(
            unquoted,
            _common.current_branch(root),
            _common.default_branch(root),
            root,
        )
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
