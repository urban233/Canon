# SPDX-License-Identifier: BSD-3-Clause
"""Read-only slice of Canon's committed config.

Deliberately duplicated (not imported) from
plugins/claude/hooks/_config.py, and deliberately trimmed: this server
only ever reads whether a verification signal exists, never writes
`.canon/config.json` and never infers a proposal for one, so
`save_config`/`suggest_verify_command` are not copied over. See
_git.py's module docstring for why hooks and this package don't share a
dependency edge.

`shell_metacharacter` and `verify_command_problem` *are* copied over,
byte-for-byte in logic if not in surrounding comments: `evidence.py`'s
`_run_local_check` runs the configured command the same way
`stop.py`'s `_run_verification` does -- `shlex.split`, no shell -- so it
has the identical compound-command bug and needs the identical guard
against it. Keep the two in sync by hand; nothing enforces that but this
comment and the pull request that adds a change to one of them.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from ._plan import read_plan_file

_CONFIG_PATH_RELATIVE = ".canon/config.json"


def load_config(root: Path) -> dict[str, Any] | None:
    """Parse `.canon/config.json`.

    Returns None on a missing file, an unreadable file, or JSON that
    isn't a top-level object. Never raises -- callers must treat None
    as "no config exists yet", never as an error to surface.
    """
    path = root / _CONFIG_PATH_RELATIVE
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def has_verification_signal(config: dict[str, Any] | None) -> bool:
    """Whether `config` names a real command that should pass before a
    turn ends. See docs/plan.md §07's "no signal, no Canon"."""
    if config is None:
        return False
    verify = config.get("verify")
    return isinstance(verify, str) and verify.strip() != ""


_PLANS_DIR_RELATIVE = ".canon/plans"


def resolve_verify_command(
    root: Path, branch: str | None, config: dict[str, Any] | None
) -> str | None:
    """The command that should pass on this branch: the plan header's
    `verify:` if it names one, else the config's.

    Duplicated from plugins/claude/hooks/_config.py under the same
    copied-and-forked rule as the rest of this module -- see _git.py's
    docstring. It exists here so a local re-run in `evidence.py` and the
    `Stop` gate can never disagree about which command counts.
    """
    if branch:
        plan = read_plan_file(root, f"{_PLANS_DIR_RELATIVE}/{branch}.md")
        if plan is not None:
            override = str(plan["header"].get("verify", "")).strip()
            if override:
                return override
    if config is None:
        return None
    verify = config.get("verify")
    return verify.strip() if isinstance(verify, str) and verify.strip() else None


def verify_command_source(
    root: Path, branch: str | None, config: dict[str, Any] | None
) -> str:
    """Where the value `resolve_verify_command` returns actually came
    from: the branch's plan header if it named one, else
    `.canon/config.json`.

    Duplicated from plugins/claude/hooks/_config.py. `evidence.py`'s
    `build_evidence` uses this to name the file a human should actually
    go fix when reporting a configuration fault -- naming
    `.canon/config.json` unconditionally would send them to edit the
    wrong file for a command that came from a plan header instead.
    """
    if branch:
        plan = read_plan_file(root, f"{_PLANS_DIR_RELATIVE}/{branch}.md")
        if plan is not None:
            override = str(plan["header"].get("verify", "")).strip()
            if override:
                return f"{_PLANS_DIR_RELATIVE}/{branch}.md"
    return _CONFIG_PATH_RELATIVE


_SHELL_METACHARACTER_PUNCTUATION = "();<>|&`$\n"
_SHELL_METACHARACTER_CHARS = frozenset("&;<>|`\n")


def shell_metacharacter(command: str) -> str | None:
    """The first shell metacharacter `command` contains outside of a
    quoted argument, or None if it contains none.

    Duplicated from plugins/claude/hooks/_config.py -- see that copy's
    docstring for the full reasoning: why `shlex.split` alone silently
    mishandles `&&`, `||`, `|`, `;`, a newline, `>`, `<`, a backtick,
    and `$(`; how "every character in a token is an operator character"
    (not "contains one") is what tells an operator from the identical
    character sitting quoted inside an argument like `pytest -k "a and
    b"` or `just test --flag='a|b'`, and what it takes to also catch a
    lone `&`, `>>`, `&>`-style combined redirects, and an operator
    sitting after a `#` (which `shlex.shlex` treats as a comment by
    default, but `shlex.split` -- what actually runs the command --
    does not); and why `$(` needs its own `startswith` check, including
    the one case that check is conservative about.
    """
    lexer = shlex.shlex(
        command, posix=True, punctuation_chars=_SHELL_METACHARACTER_PUNCTUATION
    )
    lexer.whitespace_split = True
    # Keep "\n" out of whitespace so it surfaces as punctuation instead of
    # silently acting as an ordinary token separator (see the docstring).
    lexer.whitespace = " \t\r"
    # Match what `shlex.split` actually does at verification time -- see
    # the docstring's "commenters" paragraph.
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if token and all(
            character in _SHELL_METACHARACTER_CHARS for character in token
        ):
            return token
        if token.startswith("$("):
            return "$("
        # A "$" and a "(" only stay as two tokens when whitespace
        # separates them (`$ (...)`); contiguous `$(...)` already starts
        # a token with "$(" and is caught above. This is the rare
        # fallback for the spaced-out form.
        if token == "$" and tokens[index + 1 : index + 2] == ["("]:
            return "$("
    return None


def verify_command_problem(command: str) -> str | None:
    """Why `command` cannot be run the way this server runs it --
    directly, via `shlex.split`, with no shell -- or None when it can.

    Duplicated from plugins/claude/hooks/_config.py; used by
    `evidence.py`'s `build_evidence` before it ever calls
    `_run_local_check`, so a `.canon/config.json` fault is reported as
    exactly that -- `green: None` with an explanatory `message`, the
    same shape already used for "not configured yet" -- rather than as
    `green: False`, which `ship.py`'s `_evidence_reason` reads as "the
    configured verification failed."
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"could not parse this command: {exc}"
    if not argv:
        return "this command is empty"
    metacharacter = shell_metacharacter(command)
    if metacharacter is None:
        return None
    return (
        f"this command contains `{metacharacter}`, a shell operator -- "
        "Canon runs the configured command directly, with no shell, so "
        "`&&`, `||`, `|`, `;`, a newline, `>`, `<`, a backtick, and `$(` "
        "are refused rather than silently handed to the first program as "
        "a literal argument. Wrap the sequence in a recipe or script (a "
        "Justfile recipe, an npm script, a shell script committed to the "
        "repo) and name that single command instead."
    )


_VALID_MODES = {"pair", "solo", "async"}
_DEFAULT_MODE = "solo"


def interaction_mode(config: dict[str, Any] | None) -> str:
    """Canon's one interaction-mode setting (docs/plan.md §09): "pair",
    "solo", or "async". Defaults to "solo" for a missing config, a
    missing key, or any value that isn't one of the three literals."""
    if config is None:
        return _DEFAULT_MODE
    mode = config.get("mode")
    return mode if mode in _VALID_MODES else _DEFAULT_MODE
