# SPDX-License-Identifier: BSD-3-Clause
"""Read-only slice of Canon's committed config.

Deliberately duplicated (not imported) from
plugins/claude/hooks/_config.py, and deliberately trimmed: this server
only ever reads whether a verification signal exists, never writes
`.canon/config.json` and never infers a proposal for one, so
`save_config`/`suggest_verify_command` are not copied over. See
_git.py's module docstring for why hooks and this package don't share a
dependency edge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
