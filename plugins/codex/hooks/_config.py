# SPDX-License-Identifier: BSD-3-Clause
"""Canon's committed config and the verification precondition.

`.canon/config.json` is the one piece of state a human is meant to read,
edit, and revert like any other file in the repo -- contrast
`_common.log_decision`'s gitignored diagnostic log, which is never read
back to make a decision. This module owns that file plus the predicate a
later hook (starting with `Stop`) checks before doing anything: per
docs/plan.md's Invariant III, no verification signal means Canon stays
inert rather than operating unverified.

Unlike `_common.py`, nothing here parses a hook payload -- every function
takes `root: Path` directly, so this module is trivially unit-testable
without mocking stdin.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

import _common
import plan_header

_CONFIG_PATH_RELATIVE = ".canon/config.json"

_JUSTFILE_TEST_RECIPE = re.compile(r"^test\b.*:")
_NPM_PLACEHOLDER_TEST_SCRIPT = 'echo "Error: no test specified" && exit 1'


def load_config(root: Path) -> dict[str, Any] | None:
    """Parse `.canon/config.json`.

    Returns None on a missing file, an unreadable file, or JSON that isn't
    a top-level object. Never raises -- every caller must treat None as
    "no config exists yet", never as an error to surface.
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


def save_config(root: Path, config: dict[str, Any]) -> None:
    """Write `.canon/config.json`, creating `.canon/` if needed.

    This is Canon's one committed write. It is meant to be reviewed and
    diffed like any other source file, so it is written formatted and
    stable (sorted keys, trailing newline) rather than as a minified blob.
    """
    path = root / _CONFIG_PATH_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def has_verification_signal(config: dict[str, Any] | None) -> bool:
    """Whether `config` names a real command that should pass before a
    turn ends.

    True iff `config` is not None and `config["verify"]` is a string with
    non-whitespace content. This is the precondition a later gate checks
    before doing anything -- see docs/plan.md §07's "no signal, no Canon".
    """
    if config is None:
        return False
    verify = config.get("verify")
    return isinstance(verify, str) and verify.strip() != ""


def canon_is_active(config: dict[str, Any] | None) -> bool:
    """Whether Canon may gate, guard or capture anything at all.

    docs/plan.md §07 is unambiguous: "If no command can be established,
    Canon **stays inert** rather than running without it. Not the gate
    alone -- the whole plugin." A tool whose central promise is that
    nothing ships on the agent's own word has no business operating
    where it cannot check that word.

    Delegates to `has_verification_signal` -- the condition is the same
    one -- but the name is what a call site should read, because the two
    ask different questions. `has_verification_signal` asks "can I run
    the check?"; this asks "may I act at all?"

    Two hooks deliberately do not consult this, and the reasoning is in
    docs/decisions/0001-what-inert-means.md: `stop.py`, which is the
    only path to configuring Canon in the first place, and
    `session_start.py`, which never gates anything and is how a
    developer learns Canon is inert rather than broken.
    """
    return has_verification_signal(config)


def guard_default_branch(config: dict[str, Any] | None) -> bool:
    """Whether Canon should gate edits and commits made directly on the
    default branch.

    True unless a repo's config explicitly opts out -- the one thing
    docs/plan.md §12 calls out as worth making configurable, for a
    genuinely trunk-based repo.
    """
    if config is None:
        return True
    return config.get("guard_default_branch") is not False


_VALID_MODES = {"pair", "solo", "async"}
_DEFAULT_MODE = "solo"


def interaction_mode(config: dict[str, Any] | None) -> str:
    """Canon's one interaction-mode setting (docs/plan.md §09): "pair",
    "solo", or "async".

    Defaults to "solo" -- the documented default -- for a missing
    config, a missing key, or any value that isn't one of the three
    literals. Never guessed at runtime: a hook has no controlling
    terminal to sniff (confirmed directly against both supported
    platforms' hooks references) whether the session itself is interactive or not,
    so this is config, the same shape as `verify` and
    `guard_default_branch` before it.
    """
    if config is None:
        return _DEFAULT_MODE
    mode = config.get("mode")
    return mode if mode in _VALID_MODES else _DEFAULT_MODE


def plan_verify_command(root: Path, branch: str | None) -> str | None:
    """The `verify:` a branch's saved plan header names, or None.

    docs/plan.md §07's third row: "`verify:` in a plan header |
    Overrides it for that branch | One branch, where the work needs
    something different." Never raises; a missing or malformed plan file
    is simply "no override".

    Reads through `plan_header.branch_plan_path`, not the plain
    `.canon/plans/<branch>.md` formula: a `features/<x>` branch's own
    plan is redirected to `.canon/plans/branches/features/<x>.md`, to
    avoid colliding with a feature plan of the same slug (see
    plan_header.py's module docstring). Reading the plain formula instead
    would read a `verify:` override out of the wrong plan for exactly the
    branch names that redirect exists to protect.
    """
    if not branch:
        return None
    try:
        text = plan_header.branch_plan_path(root, branch).read_text(encoding="utf-8")
    except OSError:
        return None
    verify = _common.parse_header(text).get("verify", "")
    return verify.strip() or None


def resolve_verify_command(
    root: Path, branch: str | None, config: dict[str, Any] | None
) -> str | None:
    """The command that should pass before a turn ends on this branch.

    The plan header wins over `.canon/config.json`; the config is the
    repository-wide answer and the header is the one-branch exception.

    Note what this is *not* used for: `canon_is_active`. Whether Canon
    participates at all is a repository-level question answered by the
    config alone, so a plan header cannot switch an otherwise-inert Canon
    on for one branch. The first-run question is about the repository.
    """
    override = plan_verify_command(root, branch)
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

    A caller reporting a problem with the resolved command (see
    `verify_command_problem` and `stop.py`'s `_handle_configuration_fault`)
    must name the file a human should actually go fix -- naming
    `.canon/config.json` unconditionally would send them to edit the
    wrong file for a command that came from a plan header instead.
    `config` is accepted for symmetry with `resolve_verify_command` and
    because a config-derived answer may grow a second source later; today
    the plan header is the only thing that can outrank it.

    Named through `plan_header.branch_plan_relative`, the same redirect
    `plan_verify_command` reads through -- naming the plain
    `.canon/plans/<branch>.md` formula here would send a human to fix the
    wrong file for a `features/<x>` branch, whose plan actually lives at
    `.canon/plans/branches/features/<x>.md`.
    """
    if branch and plan_verify_command(root, branch):
        return plan_header.branch_plan_relative(branch)
    return _CONFIG_PATH_RELATIVE


_SHELL_METACHARACTER_PUNCTUATION = "();<>|&`$\n"
_SHELL_METACHARACTER_CHARS = frozenset("&;<>|`\n")


def shell_metacharacter(command: str) -> str | None:
    """The first shell metacharacter `command` contains outside of a
    quoted argument, or None if it contains none.

    Canon runs the configured verify command directly, with no shell --
    `subprocess.run(shlex.split(command), ...)` in both `stop.py`'s
    `_run_verification` and canon_mcp's `_run_local_check`. `shlex.split`
    has no concept of `&&`, `||`, `|`, `;`, a newline, `>`, `<`, a
    backtick, or `$(` -- it hands each one back as a plain argument
    rather than raising. `ruff check . && pytest` becomes `['ruff',
    'check', '.', '&&', 'pytest']`; `ruff` receives `&&` as a path,
    exits non-zero for a reason that has nothing to do with the
    repository, and the `Stop` gate reports that as a failing check
    forever. This function is how `verify_command_problem` below catches
    that before it ever reaches `subprocess.run`.

    The near miss it has to get right: a metacharacter *inside* a quoted
    argument. `pytest -k "a and b"` and `just test --flag='a|b'` are
    both completely ordinary commands and must not be rejected. A
    substring scan over the raw string cannot tell the two cases apart
    -- `"a|b"` and `a|b` look identical to `"|" in command`. So rather
    than re-deriving shlex's own quoting rules by hand, this asks shlex
    itself, the same library that does the real split at verification
    time:

    `shlex.shlex` is configured with `punctuation_chars` set to exactly
    the characters above (plus the parens, so a bare `$` run directly
    into a `(` merges into one `$(` token the way adjacent punctuation
    always does in this mode) and with `commenters` cleared -- more on
    both below. Quoting still takes priority over punctuation-splitting
    in this mode -- a quote's contents are consumed as one atomic span
    before the characters inside it are ever considered for a
    punctuation split -- so a metacharacter inside `'...'` or `"..."`
    comes back fused into the surrounding word (`--flag='a|b'` tokenizes
    to the single token `--flag=a|b`), while the same character
    standalone tokenizes to its own exact token or a token built purely
    out of operator characters (`a && b` tokenizes to `['a', '&&',
    'b']`; `a &> b` tokenizes to `['a', '&>', 'b']`).

    A token counts as an operator when *every* character in it is one of
    `_SHELL_METACHARACTER_CHARS` -- deliberately "all characters," not
    "contains a character": `--flag='a|b'` *contains* `|` but is not
    *made of* only operator characters, so it reads as content, exactly
    the distinction the near miss above needs. This single rule is what
    catches every operator shlex's punctuation-merging can produce from
    these characters, not just the two-character ones this function used
    to special-case: a lone `&` (background), `>>` (append), `&>` and
    `1>&2`-style merges (combined redirects), a lone `;`, and so on --
    confirmed directly against `pytest 2>&1`, `ruff check . & pytest`,
    `pytest &`, `pytest >> log`, and `pytest &> log`, none of which the
    exact-membership version this replaced would catch.

    A second deliberate over-rejection, the same family as `$(`'s below:
    a *wholly quoted* argument made only of operator characters --
    `cmd "|"`, `cmd '&&'`, `find . -exec cmd {} \\;` -- is rejected too,
    the same as the bare operator would be. shlex strips the quotes
    before this function ever sees the token, so `"|"` and a bare `|`
    both arrive as the single-character token `|`; there is no way to
    tell them apart without re-deriving shlex's own quote tracking by
    hand, which is exactly what asking shlex directly (rather than
    scanning the raw string) is meant to avoid. This fails in the safe
    direction -- a block-once with a named, fixable reason, never a
    silent mis-split -- so it is kept rather than special-cased away.

    `commenters` defaults to `"#"` in `shlex.shlex` but to `""` in
    `shlex.split` -- confirmed directly, and easy to miss because the
    two normally agree. Left at the default here, this function would
    stop reading at a `#` and never see an operator sitting after one,
    while `shlex.split` -- what actually runs the command -- treats `#`
    as an ordinary character and passes everything after it straight
    through as more arguments. `just test # && ruff check .` is exactly
    that: read with the default `commenters`, this function sees only
    `just test` and reports no problem, while `_run_verification` still
    receives `&&` as a literal argument. Clearing `commenters` makes
    this function see what the real split actually does.

    `$(` gets separate handling because it is the one operator made of
    two *different* punctuation characters that only merge by sitting
    next to each other, so the "every character is an operator
    character" rule above does not cover it -- `(` is deliberately left
    out of `_SHELL_METACHARACTER_CHARS`, on purpose, so that `(` and `)`
    stay inert everywhere else. That is what keeps `<(` -- process
    substitution syntax a real shell would treat specially, but this
    function does not need to reject, since `shlex.split` just hands it
    to the first program as a literal, malformed-looking argument rather
    than silently doing something else -- from being caught by the same
    rule that catches a bare `<`: the merged token `<(` contains a `(`,
    so it fails "every character is an operator character," the same
    way `cmd (a)`'s bare `(` does. `$(` does not get that protection,
    because unlike `<(` it is a real, common way to smuggle a
    substitution into an argument `shlex.split` will not perform, so a
    token starting with `$(` is treated as unsafe even in the one case
    this is conservative about: a whole argument that is quoted and
    happens to look like a substitution (`"$(x)"` alone, with nothing
    else in it) is rejected too, rather than trying to also prove it was
    quoted. That is a deliberate trade for a construct no real verify
    command is shaped like, not an oversight -- contrast a prefixed,
    genuinely-quoted use such as `--flags="$(x)"`, which still reads
    clean, because that token is `--flags=$(x)` and does not start with
    `$(`.

    An unterminated quote makes shlex raise `ValueError` while reading
    the stream; that is a different, already-handled problem (see
    `verify_command_problem`, and the identical `ValueError` caught in
    `_run_verification`/`_run_local_check`), so this returns None rather
    than raising -- "no metacharacter found" is a true statement even
    when the command cannot be fully parsed.
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


# Programs whose job is to interpret a command *string*. Names only --
# `PurePosixPath(...).name` strips any directory, so `/bin/sh` and `sh`
# are the same entry.
_SHELL_PROGRAMS = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "dash",
        "ksh",
        "ksh93",
        "mksh",
        "ash",
        "csh",
        "tcsh",
        "fish",
    }
)


def shell_wrapper(argv: list[str]) -> str | None:
    """The shell `argv` asks to interpret a command string, or None.

    `shell_metacharacter` cannot catch this one and should not try. Its
    rule is that a token made *entirely* of operator characters is an
    operator, which is what keeps a legitimately quoted argument -- the
    `"a and b"` in `pytest -k "a and b"`, a regex with a `|` in it --
    from being mistaken for one. But quoting is exactly what hides the
    operator in `sh -c "ruff check . && pytest"`: `shlex.split` yields
    `['sh', '-c', 'ruff check . && pytest']`, no token is all operator
    characters, and the string sails through to be handed to a real
    shell -- precisely what
    docs/decisions/0005-verify-command-never-runs-through-a-shell.md
    exists to rule out.

    So this is a second, separate fault rather than a widening of the
    first: not "the command contains an operator" but "the command *is*
    a shell, invoked to parse something". An eval run on 2026-09-19
    found a model reaching for this form unprompted, one turn after
    correctly explaining why the compound command it replaces was
    refused -- the refusal it had just relayed taught it the shape of
    the workaround.

    Only the `-c` family is refused. A shell running a *script* --
    `bash scripts/verify.sh` -- is the wrapper Canon actively
    recommends, exits with that script's status, and is left alone: the
    ambiguity this guards against comes from operator grammar inside an
    inline string, not from the interpreter being a shell.

    Not caught: an indirection that puts the shell somewhere other than
    `argv[0]`, such as `env sh -c ...` or `busybox sh -c ...`. Those are
    left to `suggest_verify_command`'s conventions and to review rather
    than chased here, on the same "name the characters, not the tokens"
    reasoning as `shell_metacharacter`'s message -- an enumeration of
    every indirection would drift out of date faster than it earned.
    """
    if not argv:
        return None
    program = PurePosixPath(argv[0]).name
    if program not in _SHELL_PROGRAMS:
        return None
    for argument in argv[1:]:
        # `--` ends option parsing; what follows is a script path.
        if argument == "--":
            return None
        # A bare `-` is stdin, and the first non-option argument is the
        # script -- neither is an inline command string.
        if argument == "-" or not argument.startswith("-"):
            return None
        if argument.startswith("--"):
            if argument == "--command":
                return program
            continue
        # Short options cluster: `-lc` and `-ec` carry `-c` with them.
        if "c" in argument[1:]:
            return program
    return None


def verify_command_problem(command: str) -> str | None:
    """Why `command` cannot be run the way Canon runs it -- directly, via
    `shlex.split`, with no shell -- or None when it can.

    Two distinct faults, and both are configuration problems rather
    than anything a red run would mean: shlex cannot parse the string
    at all (unbalanced quoting), or it parses fine but contains a shell
    metacharacter -- see `shell_metacharacter` -- that a real shell
    would act on and that `shlex.split` instead hands to the first
    program as a literal argument.

    Callers check this *before* ever attempting to run the command:
    `stop.py`'s `main` and canon_mcp's `evidence.py` both must report a
    positive result here as a `.canon/config.json` problem, never as a
    failing check -- see docs/plan.md §07's "wrong-but-plausible is
    worse than absent," and the reason Canon refuses rather than runs a
    compound command through a shell in the first place: a partial
    failure inside a chain is exactly the ambiguous evidence the `Stop`
    gate exists to eliminate, so "which half was red" must never be a
    question Canon has to answer.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"could not parse this command: {exc}"
    if not argv:
        return "this command is empty"
    shell = shell_wrapper(argv)
    if shell is not None:
        return (
            f"this command hands its work to `{shell}` to interpret. Canon "
            "runs the configured command directly, with no shell, so "
            f'wrapping a sequence in `{shell} -c "..."` does not make it '
            "runnable -- it just moves the shell inside the string, where "
            "the same ambiguity this refusal exists to prevent comes back "
            "with nothing able to see it. The fix is a named command that "
            "exits once, with one status: a Justfile recipe, an npm "
            "script, or a shell script committed to the repository, with "
            "that single command configured here. Propose it to the "
            "developer rather than writing it -- editing this "
            "repository's build configuration is not Canon's job."
        )
    metacharacter = shell_metacharacter(command)
    if metacharacter is None:
        return None
    # Describes the character set `shell_metacharacter` checks against,
    # not an enumerated list of tokens -- an earlier version of this
    # message listed `&&`, `||`, `|`, `;`, a newline, `>`, `<`, a
    # backtick, and `$(` explicitly, which stopped matching what the
    # detector actually catches the moment it grew past exact-token
    # matching (round 2 added a lone `&`, `>>`, `&>`/`2>&1`-style merges,
    # and more): the operator named at the start of this message no
    # longer necessarily appeared anywhere in this list. Naming the
    # *characters* instead of the tokens keeps the two from drifting
    # apart again the next time the detector's coverage grows. The
    # closing advice is conditional -- "if the real answer is a
    # sequence" -- because it is right for `a && b` and simply wrong for
    # `pytest 2>&1`, which is not a sequence at all.
    return (
        f"this command contains `{metacharacter}`, which Canon can't run "
        "as configured -- it runs the configured command directly, with "
        "no shell, so anything built from `&`, `;`, `|`, `<`, `>`, a "
        "backtick, or a newline -- `&&`, `||`, a pipe, a `;`-separated "
        "sequence, a redirection such as `>`, `>>`, or `2>&1` -- plus "
        "`$(`, is refused rather than silently handed to the first "
        "program as a literal argument. If the real answer is a "
        "sequence, wrap it in a recipe or script (a Justfile recipe, an "
        "npm script, a shell script committed to the repo) and name that "
        "single command instead."
    )


def fast_check_command(config: dict[str, Any] | None) -> str | None:
    """The fast command that should pass after an edit, or None.

    docs/plan.md §11 describes three quality layers at three latencies,
    and this is the first of them: cheap, immediate, and with no
    authority at all. `verify` answers "can this turn end?" and belongs
    to the `Stop` gate; `check` answers "is the file I just wrote
    obviously wrong?" and belongs to `fast_check.py`. A repository names
    a formatter, a linter and a typechecker here -- never its tests,
    which is what `verify` is for and what makes that gate slow enough to
    be worth running only once per turn.

    Optional, and unlike `verify` its absence does **not** make Canon
    inert. §07's precondition is about being able to check the agent's
    word before a turn ends; a repository with no fast check is simply a
    repository where layer one does nothing, which is exactly what Canon
    did before this existed.

    Canon does not infer this. `suggest_verify_command` exists because
    §07 asks Canon to propose a verification command on first run, and
    that proposal is confirmed by a human before it is written. There is
    no equivalent first-run question here, so a wrong guess would be
    wrong-but-plausible with nobody asked -- the failure §07 names. A
    repository that wants layer one says so.
    """
    if config is None:
        return None
    command = config.get("check")
    return command.strip() if isinstance(command, str) and command.strip() else None


def suggest_verify_command(root: Path) -> str | None:
    """Infer a plausible "verify" command for the first-run proposal.

    This is advisory only -- nothing calls `save_config` from this
    inference alone. A human must confirm (or correct) the proposal
    before it is written, per docs/plan.md §07's "wrong-but-plausible is
    worse than absent." Checked in order, first match wins:

    1. A `Justfile` at the repo root with a top-level `test` recipe.
    2. `pyproject.toml` present, with either `[tool.pytest.ini_options]`
       or a `tests/` directory.
    3. `package.json` with a non-placeholder `scripts.test`.
    4. Any tracked `*.ipynb` file, when nothing above matched -- last
       resort, since `pytest --nbval-lax` is a fallback rather than a
       first choice.

    Returns None when nothing matches, rather than guessing.
    """
    justfile = root / "Justfile"
    try:
        text = justfile.read_text(encoding="utf-8")
    except OSError:
        text = None
    if text is not None and any(
        _JUSTFILE_TEST_RECIPE.match(line) for line in text.splitlines()
    ):
        return "just test"

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            pyproject_text = pyproject.read_text(encoding="utf-8")
        except OSError:
            pyproject_text = ""
        if "[tool.pytest.ini_options]" in pyproject_text or (root / "tests").is_dir():
            return "pytest"

    package_json = root / "package.json"
    if package_json.is_file():
        try:
            parsed = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            scripts = parsed.get("scripts")
            if isinstance(scripts, dict):
                test_script = scripts.get("test")
                if (
                    isinstance(test_script, str)
                    and test_script != _NPM_PLACEHOLDER_TEST_SCRIPT
                ):
                    return "npm test"

    for notebook in root.rglob("*.ipynb"):
        if ".ipynb_checkpoints" not in notebook.parts:
            return "pytest --nbval-lax ."

    return None
