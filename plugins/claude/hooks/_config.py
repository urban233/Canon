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
from pathlib import Path
from typing import Any

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
