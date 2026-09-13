# SPDX-License-Identifier: BSD-3-Clause
"""Read a saved plan file back.

`plan_sections` is copied verbatim from plugins/claude/hooks/_common.py
(see _git.py's module docstring for why this package doesn't import
hooks code directly). Header parsing is new: `save_plan.py` writes a
small, fixed six-or-seven-line subset of YAML (`key: "quoted value"` or
a bare `key:`), never general YAML, so `_parse_header` is a hand-rolled
parser for exactly that shape rather than a YAML library dependency.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SECTION_HEADING_PATTERN = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
_HEADER_DELIMITER = "---\n"
_HEADER_END_MARKER = "\n---\n"


def plan_sections(body: str) -> dict[str, str]:
    """Split a plan's markdown body into `## `-heading sections.

    Keys are the heading text, lowercased and stripped -- matching every
    plan this repo's own hooks write.
    """
    matches = list(_SECTION_HEADING_PATTERN.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[name] = body[start:end].strip()
    return sections


def _unescape_scalar(value: str) -> str:
    """Reverse `save_plan.py`'s `_yaml_scalar` escaping: a backslash
    always means "take the next character literally"."""
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            result.append(value[index + 1])
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _parse_header(text: str) -> dict[str, str]:
    """Parse the `key: "value"` / bare `key:` lines between a plan's two
    `---` delimiters. Unknown-shaped lines are skipped, not raised on --
    a plan file a human has since hand-edited should degrade gracefully,
    not crash the tool reading it."""
    header: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        if (
            len(raw_value) >= 2
            and raw_value.startswith('"')
            and raw_value.endswith('"')
        ):
            header[key] = _unescape_scalar(raw_value[1:-1])
        else:
            header[key] = raw_value
    return header


def _split_document(text: str) -> tuple[str, str] | None:
    """Split a saved plan file into (header text, body text), or None if
    it doesn't start with a `---` header block."""
    if not text.startswith(_HEADER_DELIMITER):
        return None
    rest = text[len(_HEADER_DELIMITER) :]
    end_index = rest.find(_HEADER_END_MARKER)
    if end_index == -1:
        return None
    header_text = rest[:end_index]
    body_text = rest[end_index + len(_HEADER_END_MARKER) :].lstrip("\n")
    return header_text, body_text


def read_plan_file(root: Path, relative_path: str) -> dict[str, Any] | None:
    """Read and parse a plan file at `relative_path` (e.g.
    `.canon/plans/<branch>.md`), relative to `root`.

    Returns None if the file doesn't exist or can't be read -- never
    raises. A file that exists but has no `---` header (hand-written,
    not produced by `save_plan.py`) is still returned, with an empty
    header and its whole content treated as the body.
    """
    path = root / relative_path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    split = _split_document(text)
    if split is None:
        return {"path": relative_path, "header": {}, "sections": plan_sections(text)}
    header_text, body_text = split
    return {
        "path": relative_path,
        "header": _parse_header(header_text),
        "sections": plan_sections(body_text),
    }
