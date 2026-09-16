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
from pathlib import Path
from typing import Any

import _common

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


_PLANS_DIR_RELATIVE = ".canon/plans"


def plan_verify_command(root: Path, branch: str | None) -> str | None:
    """The `verify:` a branch's saved plan header names, or None.

    docs/plan.md §07's third row: "`verify:` in a plan header |
    Overrides it for that branch | One branch, where the work needs
    something different." Never raises; a missing or malformed plan file
    is simply "no override".
    """
    if not branch:
        return None
    try:
        text = (root / _PLANS_DIR_RELATIVE / f"{branch}.md").read_text(encoding="utf-8")
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


_SHELL_METACHARACTER_PUNCTUATION = "();<>|&`$\n"
_SHELL_METACHARACTERS = frozenset({"&&", "||", "|", ";", ">", "<", "`", "\n", "$("})


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
    always does in this mode). Quoting still takes priority over
    punctuation-splitting in this mode -- a quote's contents are
    consumed as one atomic span before the characters inside it are
    ever considered for a punctuation split -- so a metacharacter inside
    `'...'` or `"..."` comes back fused into the surrounding word
    (`--flag='a|b'` tokenizes to the single token `--flag=a|b`), while
    the same character standalone tokenizes to its own exact token (`a
    && b` tokenizes to `['a', '&&', 'b']`). Checking each token for
    exact membership in `_SHELL_METACHARACTERS` is therefore enough to
    tell "operator" from "content" -- verified directly against both
    examples above, not just reasoned about. A newline gets the same
    treatment but needs one extra step: it is pulled out of `whitespace`
    and into `punctuation_chars`, because left in `whitespace` it would
    vanish as an ordinary token separator instead of surfacing as the
    metacharacter it is when a multi-line recipe body gets pasted in
    unquoted.

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
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if token in _SHELL_METACHARACTERS:
            return token
        # A "$" and a "(" only stay as two tokens when whitespace
        # separates them (`$ (...)`); contiguous `$(...)` already merges
        # into the single "$(" token caught by the membership check
        # above. This is the rare fallback for the spaced-out form.
        if token == "$" and tokens[index + 1 : index + 2] == ["("]:
            return "$("
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
