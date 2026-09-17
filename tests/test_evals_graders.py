# SPDX-License-Identifier: BSD-3-Clause
"""Static validation of every `claude plugin eval` case this repo ships.

A grader is a markdown file whose YAML frontmatter tells `claude plugin
eval` what to assert. Nothing checks that frontmatter today, and a
malformed grader is not inert -- it fails, deterministically, for a
reason that has nothing to do with the instruction text under test. That
costs a **paid** run to discover: every eval run is a real model call
billed to the account (see
docs/decisions/0003-eval-suite-is-not-a-ci-gate.md), so a grader that
could never have passed burns quota to report a bug in itself.

This happened. `save-plan-redirects-a-features-prefixed-branch`'s
`the-seeded-feature-plan-is-not-modified` grader originally asserted a
file's *contents* against `target: files`, which matches a
newline-separated list of the *paths* created during the run. No path
list can contain `status: approved\\nsteps:`, so the grader was
unpassable regardless of the code, and only an independent review caught
it before the run was spent.

Why this is a `bazel test` and part of `just ci`, when
docs/decisions/0003 keeps the eval suite out of CI: 0003 bars wiring
`claude plugin eval` -- the billed, model-backed run -- into CI, and
explicitly leaves "everything `just ci` already runs" unaffected. This
module makes no model call and needs no credential. It parses text.

Standard library only, and it reads the **raw** frontmatter rather than
parsing YAML, because one of the rules below is about quoting and a
parser erases exactly the evidence it needs.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

# Deliberately not `.resolve()`: a runfiles entry is an absolute symlink
# back into the source tree, so resolving it walks out of the runfiles
# and the test would read the working tree no matter what Bazel
# delivered -- which would make the vacuity guard below a no-op.
_REPO_ROOT = Path(__file__).parent.parent
_EVAL_SUITES = ("plugins/claude/evals", "plugins/canon-companion/evals")
# Directories the eval CLI owns rather than cases anyone wrote.
# `claude plugin eval` writes its results under `<eval dir>/results/`
# (already gitignored) and reads recorded mocks from `<eval dir>/mocks/`.
# Without this, running `just eval` makes the very next `just ci` fail
# with "case.yaml is missing" pointing at a results directory -- the
# checker that exists to protect an eval run, broken by one.
_NON_CASE_DIRS = frozenset({"results", "mocks"})

_VALID_TYPES = {"llm", "regex", "tool_used"}
_VALID_SCALAR_TARGETS = {"files", "trace"}
_VALID_MATCH_MODES = {"contains", "not_contains"}

# `target: {source: file, path: <path>}` -- the file-*contents* target, as
# distinct from `target: files`, the list of created paths.
_FILE_TARGET = re.compile(r"^\{\s*source:\s*file\s*,\s*path:\s*(?P<path>[^}]+?)\s*\}$")
# A backslash that is neither preceded nor followed by another: a single
# escape. `\\d` (a doubled backslash) is a legitimate double-quoted way to
# write a literal backslash and must not trip this.
_LONE_BACKSLASH = re.compile(r"(?<!\\)\\(?!\\)")
_ANCHOR = re.compile(r"[\^$]")


def _frontmatter(text: str) -> dict[str, str]:
    """The first `---`-delimited block, as `{key: raw value}`.

    Values are kept **verbatim**, quotes included -- `_quote_style` below
    depends on that, and so does the rule about double-quoted escapes.
    Returns `{}` for a file with no frontmatter, which the caller reports
    as its own failure rather than silently skipping.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if not separator:
            continue
        fields[key.strip()] = value.strip()
    return fields


def _quote_style(raw: str) -> str:
    """`"double"`, `"single"` or `"plain"` for a scalar's quoting.

    A plain (unquoted) scalar passes backslashes through to the regex
    engine exactly as a single-quoted one does, so the two are equivalent
    for our purposes and only `double` is restricted.
    """
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return "double"
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return "single"
    return "plain"


def _unquote(raw: str) -> str:
    return raw[1:-1] if _quote_style(raw) in ("double", "single") else raw


def _case_dirs() -> list[Path]:
    cases: list[Path] = []
    for suite in _EVAL_SUITES:
        suite_path = _REPO_ROOT / suite
        if not suite_path.is_dir():
            continue
        cases.extend(
            sorted(
                p
                for p in suite_path.iterdir()
                if p.is_dir() and p.name not in _NON_CASE_DIRS
            )
        )
    return cases


def _grader_files(case: Path) -> list[Path]:
    graders = case / "graders"
    return sorted(graders.glob("*.md")) if graders.is_dir() else []


def _relative(path: Path) -> str:
    return str(path.relative_to(_REPO_ROOT))


class EvalSuiteShapeTests(unittest.TestCase):
    """The case directory itself, before any grader is read."""

    def test_at_least_one_case_is_discovered(self) -> None:
        """A guard on this module, not on the suite: if the data
        dependency is mis-wired under Bazel, every other test here would
        pass vacuously by iterating an empty list."""
        self.assertTrue(
            _case_dirs(), "no eval cases found -- is the Bazel data dep wired?"
        )

    def test_every_case_name_matches_its_directory(self) -> None:
        for case in _case_dirs():
            with self.subTest(case=_relative(case)):
                case_yaml = case / "case.yaml"
                self.assertTrue(case_yaml.is_file(), "case.yaml is missing")
                declared = ""
                for line in case_yaml.read_text(encoding="utf-8").splitlines():
                    key, separator, value = line.partition(":")
                    if separator and key.strip() == "name":
                        declared = _unquote(value.strip())
                        break
                self.assertEqual(
                    declared,
                    case.name,
                    "case.yaml's name must match its directory, or a --case glob "
                    "filter silently selects nothing",
                )

    def test_every_case_has_at_least_one_grader(self) -> None:
        """A case with no grader runs the model and scores nothing --
        it spends quota to produce no evidence."""
        for case in _case_dirs():
            with self.subTest(case=_relative(case)):
                self.assertTrue(_grader_files(case), "no graders/*.md")


class GraderFrontmatterTests(unittest.TestCase):
    """Every grader's frontmatter, rule by rule."""

    def _graders(self) -> list[tuple[Path, dict[str, str]]]:
        found = []
        for case in _case_dirs():
            for grader in _grader_files(case):
                found.append((grader, _frontmatter(grader.read_text(encoding="utf-8"))))
        return found

    def test_every_grader_has_frontmatter_with_a_known_type(self) -> None:
        for grader, fields in self._graders():
            with self.subTest(grader=_relative(grader)):
                self.assertTrue(fields, "no --- frontmatter block")
                self.assertIn(
                    _unquote(fields.get("type", "")),
                    _VALID_TYPES,
                    f"type must be one of {sorted(_VALID_TYPES)}",
                )

    def test_a_regex_grader_declares_both_pattern_and_target(self) -> None:
        for grader, fields in self._graders():
            if _unquote(fields.get("type", "")) != "regex":
                continue
            with self.subTest(grader=_relative(grader)):
                self.assertIn("pattern", fields, "a regex grader needs a pattern")
                self.assertIn(
                    "target",
                    fields,
                    "a regex grader needs a target -- without one it is not "
                    "clear what the pattern is matched against",
                )

    def test_a_tool_used_grader_declares_a_tool(self) -> None:
        for grader, fields in self._graders():
            if _unquote(fields.get("type", "")) != "tool_used":
                continue
            with self.subTest(grader=_relative(grader)):
                self.assertIn("tool", fields, "a tool_used grader needs a tool")

    def test_every_target_is_a_known_form(self) -> None:
        for grader, fields in self._graders():
            if "target" not in fields:
                continue
            with self.subTest(grader=_relative(grader)):
                raw = fields["target"]
                if _unquote(raw) in _VALID_SCALAR_TARGETS:
                    continue
                match = _FILE_TARGET.match(raw)
                self.assertIsNotNone(
                    match,
                    "target must be `files`, `trace`, or a "
                    "`{source: file, path: <path>}` mapping",
                )
                assert match is not None
                path = match.group("path")
                self.assertFalse(
                    path.startswith("/"),
                    "a file target's path is relative to the run's working tree",
                )

    def test_a_files_target_is_matched_line_by_line(self) -> None:
        """`target: files` is a newline-separated list of the paths
        created during the run, so a pattern against it must be anchored
        AND multiline.

        This is the rule that catches the real bug. An unanchored pattern
        against `files` is almost always someone reaching for file
        *contents*, which needs `target: {source: file, path: ...}`
        instead. And an anchor without `flags: m` anchors the whole blob
        rather than each line, which silently matches nothing after the
        first path -- so the two have to be required together.
        """
        for grader, fields in self._graders():
            if _unquote(fields.get("target", "")) != "files":
                continue
            with self.subTest(grader=_relative(grader)):
                pattern = _unquote(fields.get("pattern", ""))
                self.assertRegex(
                    pattern,
                    _ANCHOR,
                    "a `target: files` pattern must anchor with ^ or $ -- an "
                    "unanchored one is usually a file-contents assertion, which "
                    "needs `target: {source: file, path: ...}`",
                )
                self.assertIn(
                    "m",
                    _unquote(fields.get("flags", "")),
                    "a `target: files` pattern needs `flags: m`, or ^ and $ "
                    "anchor the whole path list instead of each line",
                )

    def test_a_double_quoted_pattern_has_no_lone_backslash_escape(self) -> None:
        """In a double-quoted YAML scalar the parser consumes escapes
        before the regex engine ever sees them, so `"\\n"` reaches the
        engine as a literal newline rather than as the escape the author
        meant. Single-quoted and plain scalars both pass backslashes
        through untouched, and a doubled `\\\\d` is a legitimate
        double-quoted way to write one -- only a lone escape is wrong.
        """
        for grader, fields in self._graders():
            for key in ("pattern", "input_match"):
                raw = fields.get(key)
                if raw is None or _quote_style(raw) != "double":
                    continue
                with self.subTest(grader=_relative(grader), key=key):
                    self.assertIsNone(
                        _LONE_BACKSLASH.search(_unquote(raw)),
                        f"{key} is double-quoted and contains a lone backslash "
                        "escape -- single-quote it so the escape survives YAML",
                    )

    def test_every_match_mode_is_known(self) -> None:
        for grader, fields in self._graders():
            if "match" not in fields:
                continue
            with self.subTest(grader=_relative(grader)):
                self.assertIn(
                    _unquote(fields["match"]),
                    _VALID_MATCH_MODES,
                    f"match must be one of {sorted(_VALID_MATCH_MODES)}",
                )


if __name__ == "__main__":
    unittest.main()
