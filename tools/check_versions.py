# SPDX-License-Identifier: BSD-3-Clause
"""Fail if Canon's version is not stated identically everywhere.

Canon declares its version in eleven places today: two plugin manifests
and one marketplace file per harness, two `pyproject.toml` files, the
Bazel module, and three generated copies. `just sync-check` already
guards the generated three against their sources. Nothing guarded the
rest against each other, so `just ci` was green with versions that
disagreed -- which is how estimating the 0.1.0 bump produced "six
version strings" for a tree that had eleven.

**This discovers the files rather than listing them**, and that is the
whole design. A hardcoded list is the failure this repository has
already hit twice: `.github/workflows/ci.yml` hand-copied `just ci`'s
recipe list and silently omitted `sync-check`, and the skills drift
guard iterated four names and said nothing about a fifth. A list here
would go stale the first time a plugin is added, and it would go stale
silently, which is the only way that matters. So a new manifest is
covered the day it lands.

Exit status is 0 when every discovered version agrees with every other
and with the newest entry in `CHANGELOG.md`, 1 otherwise, with each
disagreeing file named. Run it from the repository root.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

# Directories that can hold a `pyproject.toml` or `plugin.json` which is
# not Canon's own: Bazel's convenience symlinks point into the output
# tree (thousands of third-party manifests), and `.git` can hold
# anything a hook or a worktree left there. `.claude` carries agent
# worktrees, which are whole second checkouts of this repository -- see
# .bazelignore, which excludes it for the same reason.
_EXCLUDED_DIR_NAMES = frozenset({".git", ".claude", "__pycache__", "node_modules"})
_EXCLUDED_DIR_PREFIXES = ("bazel-",)

# `version = "1.2.3"` on its own line, which is a pyproject's `[project]`
# form. Matching it textually avoids needing `tomllib`, which is 3.11+ --
# this script runs on whatever `python3` the developer has, down to the
# 3.9 floor pyproject.toml advertises.
_VERSION_ASSIGNMENT = re.compile(r'^\s*version\s*=\s*"([^"]+)"', re.MULTILINE)

# MODULE.bazel states its version *inside* a call --
# `module(name = "canon", version = "0.1.0")` -- so the line-anchored
# pattern above does not see it. It had its own pattern from the first
# run of this check, which reported ten files for a tree with eleven:
# a version-agreement check that silently skips a file is the exact
# failure it exists to prevent, so the two forms are matched separately
# and deliberately rather than by loosening the anchor, which would
# start matching any `version = "..."` in any table of any TOML file.
_MODULE_BAZEL_VERSION = re.compile(
    r'\bmodule\s*\([^)]*\bversion\s*=\s*"([^"]+)"', re.DOTALL
)

# The newest `## [1.2.3]` heading in a Keep a Changelog file. `[Unreleased]`
# is deliberately not matched: an unreleased section is not a version
# claim, and treating it as one would make the check fail for a
# repository mid-cycle.
_CHANGELOG_HEADING = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]", re.MULTILINE)

_CHANGELOG_PATH = "CHANGELOG.md"

# Everything from a `## [1.2.3]` heading up to the next `## ` heading or
# the link-reference block at the foot of the file, which is this
# version's release notes. Read by the release workflow so the notes a
# reader sees are the notes in the repository -- not a second, drifting
# copy written into a GitHub release by hand.
_CHANGELOG_SECTION = r"^##\s+\[{version}\][^\n]*\n(.*?)(?=^##\s+\[|^\[{version}\]:|\Z)"


class Finding(NamedTuple):
    """One file's declared version, for reporting a disagreement."""

    path: str
    version: str


def _is_excluded(path: Path) -> bool:
    """Whether `path` lies under a directory this check must not read."""
    for part in path.parts:
        if part in _EXCLUDED_DIR_NAMES:
            return True
        if any(part.startswith(prefix) for prefix in _EXCLUDED_DIR_PREFIXES):
            return True
    return False


def _json_versions(root: Path) -> list[Finding]:
    """Every `"version"` declared by a plugin or marketplace manifest.

    A marketplace file carries one version per listed plugin, so its
    entries are reported individually -- `plugins[0]` disagreeing with
    `plugins[1]` is exactly the kind of mismatch worth naming precisely.
    """
    findings: list[Finding] = []
    for pattern in ("**/plugin.json", "**/marketplace.json"):
        for path in sorted(root.glob(pattern)):
            if _is_excluded(path.relative_to(root)):
                continue
            relative = str(path.relative_to(root))
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                print(f"{relative}: cannot be read as JSON ({error})", file=sys.stderr)
                raise SystemExit(1) from error
            if not isinstance(data, dict):
                continue
            own = data.get("version")
            if isinstance(own, str):
                findings.append(Finding(relative, own))
            listed = data.get("plugins")
            if isinstance(listed, list):
                for index, entry in enumerate(listed):
                    if not isinstance(entry, dict):
                        continue
                    entry_version = entry.get("version")
                    if isinstance(entry_version, str):
                        name = entry.get("name")
                        label = name if isinstance(name, str) else str(index)
                        findings.append(Finding(f"{relative} [{label}]", entry_version))
    return findings


def _assignment_versions(root: Path) -> list[Finding]:
    """Every version assigned in a `pyproject.toml` or `MODULE.bazel`.

    Only the first assignment in a file is read. A `pyproject.toml` has
    exactly one `version =` under `[project]`; a later one would belong
    to some tool's own table and is not Canon's version to police.
    """
    findings: list[Finding] = []
    for pattern, expression in (
        ("**/pyproject.toml", _VERSION_ASSIGNMENT),
        ("**/MODULE.bazel", _MODULE_BAZEL_VERSION),
    ):
        for path in sorted(root.glob(pattern)):
            if _is_excluded(path.relative_to(root)):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as error:
                relative = str(path.relative_to(root))
                print(f"{relative}: cannot be read ({error})", file=sys.stderr)
                raise SystemExit(1) from error
            match = expression.search(text)
            if match is not None:
                findings.append(Finding(str(path.relative_to(root)), match.group(1)))
    return findings


def changelog_version(root: Path) -> str | None:
    """The newest released version in `CHANGELOG.md`, or None if there
    is no changelog or it names no released version yet."""
    path = root / _CHANGELOG_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _CHANGELOG_HEADING.search(text)
    return match.group(1) if match else None


def changelog_section(root: Path, version: str) -> str | None:
    """This version's release notes, taken verbatim from `CHANGELOG.md`."""
    path = root / _CHANGELOG_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    pattern = re.compile(
        _CHANGELOG_SECTION.format(version=re.escape(version)),
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def declared_versions(root: Path) -> list[Finding]:
    """Every version this repository declares, from every file that
    declares one."""
    return _json_versions(root) + _assignment_versions(root)


def main(argv: list[str]) -> int:
    """Verify, then optionally print what was verified.

    `--print` and `--notes` both verify first and fail the same way an
    ordinary run does. That ordering is the point: neither mode can ever
    report a version the repository does not consistently declare, so
    the release workflow cannot tag something this check would have
    rejected.
    """
    mode = argv[0] if argv else ""
    if mode not in ("", "--print", "--notes"):
        print(
            f"unknown argument {mode!r}; expected --print or --notes",
            file=sys.stderr,
        )
        return 2

    root = Path.cwd()
    findings = declared_versions(root)

    if not findings:
        print(
            "no version-bearing file found -- check_versions.py is looking in the "
            "wrong place, or it is not being run from the repository root",
            file=sys.stderr,
        )
        return 1

    distinct = sorted({finding.version for finding in findings})
    if len(distinct) > 1:
        print(
            f"versions disagree: {', '.join(distinct)}",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding.version}  {finding.path}", file=sys.stderr)
        print(
            "\nevery file above must state the same version; the generated "
            "copies move via 'just sync-mcp' and 'just sync-manifests'",
            file=sys.stderr,
        )
        return 1

    declared = distinct[0]
    newest = changelog_version(root)
    if newest is None:
        print(
            f"{_CHANGELOG_PATH} names no released version, but every manifest "
            f"declares {declared} -- add its entry before releasing",
            file=sys.stderr,
        )
        return 1
    if newest != declared:
        print(
            f"{_CHANGELOG_PATH}'s newest entry is {newest}, but every manifest "
            f"declares {declared}",
            file=sys.stderr,
        )
        return 1

    if mode == "--print":
        print(declared)
        return 0

    if mode == "--notes":
        section = changelog_section(root, declared)
        if not section:
            print(
                f"{_CHANGELOG_PATH} has no readable section for {declared}",
                file=sys.stderr,
            )
            return 1
        print(section)
        return 0

    print(
        f"version {declared} agrees across {len(findings)} files and {_CHANGELOG_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
