# SPDX-License-Identifier: BSD-3-Clause
"""The one place in Canon that knows what a notebook is.

docs/plan.md §07 makes this a deliberate exception rather than an
oversight. The purer position -- decline to review until the repository
configures `nbstripout` or `jupytext` -- keeps the
recommend-don't-reimplement line unbroken, but it makes Canon precious
about a file format its users open every day and useless on day one in a
repository nobody has set up yet. "Fifteen lines buys a great deal of
that back."

So this module extracts `cell["source"]` where `cell_type == "code"`,
and counts code cells. That is the whole of it. What Canon still never
does: install `nbstripout`, configure `jupytext`, strip outputs, rewrite
a notebook, or render a diff.

Deliberately not duplicated into plugins/claude/hooks/: the hooks' only
notebook concern is noticing that a repository has `.ipynb` files with
neither tool configured, which needs no cell parsing. Cell extraction
and counting are review-time questions, and review runs through this
package.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

_NOTEBOOK_SUFFIX = ".ipynb"
_JUPYTEXT_CONFIG_NAMES = ("jupytext.toml", ".jupytext.toml", "jupytext.yml")


def is_notebook(path: str) -> bool:
    return path.lower().endswith(_NOTEBOOK_SUFFIX)


def _cell_source(cell: Any) -> str:
    """One cell's source, whether stored as a list of lines or a string.

    Both shapes are valid nbformat and both occur in the wild, so this
    accepts either rather than assuming the one a given tool writes.
    """
    if not isinstance(cell, dict):
        return ""
    source = cell.get("source")
    if isinstance(source, list):
        return "".join(part for part in source if isinstance(part, str))
    return source if isinstance(source, str) else ""


def code_cell_sources(text: str) -> list[str] | None:
    """Every code cell's source, in order, or None if `text` is not a
    readable notebook. Never raises -- an unreadable notebook is "I
    can't tell you", not an error to surface."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    cells = parsed.get("cells")
    if not isinstance(cells, list):
        return None
    return [
        _cell_source(cell)
        for cell in cells
        if isinstance(cell, dict) and cell.get("cell_type") == "code"
    ]


def changed_code_cells(before: str | None, after: str | None) -> int | None:
    """How many code cells differ between two versions of a notebook.

    §07: "Counts **code cells changed** rather than lines when the file
    is `.ipynb`. Deterministic, and it makes the small-change discipline
    measurable again." Line counts mean nothing for a format where a
    one-line semantic change arrives with `execution_count` churn and
    re-serialised output.

    A missing `before` is a new notebook: every code cell is changed.
    None when either side cannot be parsed.
    """
    after_cells = code_cell_sources(after) if after is not None else None
    if after_cells is None:
        return None
    if before is None:
        return len(after_cells)
    before_cells = code_cell_sources(before)
    if before_cells is None:
        return None
    matcher = difflib.SequenceMatcher(a=before_cells, b=after_cells, autojunk=False)
    changed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed += max(i2 - i1, j2 - j1)
    return changed


def paired_script(root: Path, notebook_path: str) -> str | None:
    """The jupytext `.py` paired with this notebook, if one is there.

    Pairing is detected by the file simply existing next to the
    notebook, rather than by parsing a jupytext config: the config has
    several shapes and the question Canon actually has is "is there a
    readable form I can hand the reviewer", which the file answers
    directly.
    """
    candidate = Path(notebook_path).with_suffix(".py")
    return str(candidate) if (root / candidate).is_file() else None


def has_readable_form_configured(root: Path) -> bool:
    """Whether the repository already provides a readable form for its
    notebooks -- an `nbstripout` git filter or a jupytext config.

    §07: Canon "recommends and never installs", so this only ever
    reports.
    """
    try:
        attributes = (root / ".gitattributes").read_text(encoding="utf-8")
    except OSError:
        attributes = ""
    for line in attributes.splitlines():
        if _NOTEBOOK_SUFFIX in line and "filter=" in line:
            return True
    if any((root / name).is_file() for name in _JUPYTEXT_CONFIG_NAMES):
        return True
    try:
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool.jupytext" in pyproject
