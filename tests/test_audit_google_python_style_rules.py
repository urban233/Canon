"""Rule-level coverage for the companion Google Python Style checker.

Each rule carries a triggering source and a corrected source. The corrected
source is the control that catches a false positive, which matters here
because SKILL.md Phase B repeats the checker until no violation-level finding
remains: every false positive becomes a mandated edit to correct code.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = (
    ROOT
    / "plugins/canon-companion/skills/audit-google-python-style/scripts"
    / "check_google_rules.py"
)


def load_checker() -> Any:
    """Load the bundled standalone checker from its installed plugin path.

    Returns:
        The imported checker module.
    """
    spec = importlib.util.spec_from_file_location(
        "google_style_rule_checker", CHECKER_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


# One triggering source and one corrected source per rule. The corrected
# source is the real control: a checker that never fires passes only the
# triggering half, and a checker that fires on correct code passes only the
# corrected half.
RULE_CASES: dict[str, tuple[str, str]] = {
    "absolute-imports": (
        '"""Sample module."""\n\nfrom . import sibling\n\n\nVALUE = sibling\n',
        '"""Sample module."""\n\nimport pkg.sibling\n\n\nVALUE = pkg.sibling\n',
    ),
    "assertion-control-flow": (
        '''"""Sample module."""


def check(value):
    """Check a value.

    Args:
        value: Value to check.

    Returns:
        The value.
    """
    assert value, "value is required"
    return value
''',
        '''"""Sample module."""


def check(value):
    """Check a value.

    Args:
        value: Value to check.

    Returns:
        The value.

    Raises:
        ValueError: If the value is missing.
    """
    if not value:
        raise ValueError("value is required")
    return value
''',
    ),
    "binding-naming": (
        '"""Sample module."""\n\nrowCount = 3\n',
        '"""Sample module."""\n\nrow_count = 3\n',
    ),
    "broad-exception": (
        '''"""Sample module."""


def run(action):
    """Run an action.

    Args:
        action: Callable to run.

    Returns:
        Whether the action succeeded.
    """
    try:
        action()
    except Exception:
        return False
    return True
''',
        '''"""Sample module."""


def run(action):
    """Run an action.

    Args:
        action: Callable to run.

    Returns:
        Whether the action succeeded.
    """
    try:
        action()
    except ValueError:
        return False
    return True
''',
    ),
    "class-naming": (
        '"""Sample module."""\n\n\nclass row_holder:\n    """Hold rows."""\n',
        '"""Sample module."""\n\n\nclass RowHolder:\n    """Hold rows."""\n',
    ),
    "comment-markup": (
        '"""Sample module."""\n\n# Set the `value` binding.\nvalue = 1\n',
        '"""Sample module."""\n\n# Set the value binding.\nvalue = 1\n',
    ),
    "comment-punctuation": (
        '"""Sample module."""\n\n# Set the value binding\nvalue = 1\n',
        '"""Sample module."""\n\n# Set the value binding.\nvalue = 1\n',
    ),
    "docstring-args": (
        '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Returns:
        A summary.
    """
    return rows
''',
        '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Args:
        rows: Rows to summarize.

    Returns:
        A summary.
    """
    return rows
''',
    ),
    "docstring-markup": (
        '"""Sample module with a `backtick`."""\n',
        '"""Sample module without markup."""\n',
    ),
    "docstring-raises": (
        '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Args:
        rows: Rows to summarize.

    Returns:
        A summary.
    """
    if not rows:
        raise ValueError("rows is required")
    return rows
''',
        '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Args:
        rows: Rows to summarize.

    Returns:
        A summary.

    Raises:
        ValueError: If rows is empty.
    """
    if not rows:
        raise ValueError("rows is required")
    return rows
''',
    ),
    "docstring-returns": (
        '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Args:
        rows: Rows to summarize.
    """
    return rows
''',
        '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Args:
        rows: Rows to summarize.

    Returns:
        A summary.
    """
    return rows
''',
    ),
    "docstring-section-punctuation": (
        '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Args:
        rows: Rows to summarize

    Returns:
        A summary.
    """
    return rows
''',
        '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Args:
        rows: Rows to summarize.

    Returns:
        A summary.
    """
    return rows
''',
    ),
    "docstring-summary": (
        '"""Sample module"""\n',
        '"""Sample module."""\n',
    ),
    "docstring-yields": (
        '''"""Sample module."""


def stream(rows):
    """Stream rows.

    Args:
        rows: Rows to stream.
    """
    yield from rows
''',
        '''"""Sample module."""


def stream(rows):
    """Stream rows.

    Args:
        rows: Rows to stream.

    Yields:
        One row at a time.
    """
    yield from rows
''',
    ),
    "explicit-line-continuation": (
        '"""Sample module."""\n\ntotal = 1 + \\\n    2\n',
        '"""Sample module."""\n\ntotal = (\n    1 + 2\n)\n',
    ),
    "function-naming": (
        '''"""Sample module."""


def buildReport():
    """Build a report.

    Returns:
        A report.
    """
    return {}
''',
        '''"""Sample module."""


def build_report():
    """Build a report.

    Returns:
        A report.
    """
    return {}
''',
    ),
    "lambda-expression": (
        '"""Sample module."""\n\ndouble = lambda value: value * 2\n',
        '''"""Sample module."""


def double(value):
    """Double a value.

    Args:
        value: Value to double.

    Returns:
        Twice the value.
    """
    return value * 2
''',
    ),
    "legacy-typing-alias": (
        '"""Sample module."""\n\nimport typing\n\nROWS: typing.List[int] = []\n',
        '"""Sample module."""\n\nROWS: list[int] = []\n',
    ),
    "line-length": (
        '"""Sample module."""\n\nvalue = "' + "x" * 90 + '"\n',
        '"""Sample module."""\n\nvalue = "short"\n',
    ),
    "module-docstring": (
        "value = 1\n",
        '"""Sample module."""\n\nvalue = 1\n',
    ),
    "multiple-from-imports": (
        '''"""Sample module."""

from os import getcwd, sep


VALUE = (getcwd, sep)
''',
        '''"""Sample module."""

import os


VALUE = (os.getcwd, os.sep)
''',
    ),
    "multiple-imports": (
        '"""Sample module."""\n\nimport os, sys\n\n\nVALUE = (os, sys)\n',
        '"""Sample module."""\n\nimport os\nimport sys\n\n\nVALUE = (os, sys)\n',
    ),
    "mutable-default": (
        '''"""Sample module."""


def summarize(rows, totals=[]):
    """Summarize rows.

    Args:
        rows: Rows to summarize.
        totals: Running totals.

    Returns:
        A summary.
    """
    return rows, totals
''',
        '''"""Sample module."""


def summarize(rows, totals=None):
    """Summarize rows.

    Args:
        rows: Rows to summarize.
        totals: Running totals.

    Returns:
        A summary.
    """
    return rows, totals
''',
    ),
    "mutable-global-state": (
        '"""Sample module."""\n\ncache = {}\n',
        '"""Sample module."""\n\nCACHE = {}\n',
    ),
    "nested-class": (
        '''"""Sample module."""


class Outer:
    """Outer class."""

    class Inner:
        """Inner class."""
''',
        '''"""Sample module."""


class Inner:
    """Inner class."""


class Outer:
    """Outer class."""
''',
    ),
    "nested-function": (
        '''"""Sample module."""


def outer():
    """Outer function.

    Returns:
        The inner result.
    """

    def inner():
        """Inner function.

        Returns:
            A value.
        """
        return 1

    return inner()
''',
        '''"""Sample module."""


def inner():
    """Inner function.

    Returns:
        A value.
    """
    return 1


def outer():
    """Outer function.

    Returns:
        The inner result.
    """
    return inner()
''',
    ),
    "no-typing-text": (
        '"""Sample module."""\n\nimport typing\n\nNAME: typing.Text = "a"\n',
        '"""Sample module."""\n\nNAME: str = "a"\n',
    ),
    "no-wildcard-imports": (
        '"""Sample module."""\n\nfrom os.path import *\n',
        '"""Sample module."""\n\nimport os.path\n\n\nVALUE = os.path.sep\n',
    ),
    "parameter-naming": (
        '''"""Sample module."""


def summarize(rowCount):
    """Summarize rows.

    Args:
        rowCount: Number of rows.

    Returns:
        A summary.
    """
    return rowCount
''',
        '''"""Sample module."""


def summarize(row_count):
    """Summarize rows.

    Args:
        row_count: Number of rows.

    Returns:
        A summary.
    """
    return row_count
''',
    ),
    "ruff-suppression": (
        '"""Sample module."""\n\n# pylint: disable=invalid-name.\nvalue = 1\n',
        '"""Sample module."""\n\n# noqa is scoped to its own line.\nvalue = 1\n',
    ),
    "semicolons": (
        '"""Sample module."""\n\ntotal = 0; count = 0\n',
        '"""Sample module."""\n\ntotal = 0\ncount = 0\n',
    ),
    "tmp-prefix": (
        '"""Sample module."""\n\ntmp_rows = []\n',
        '"""Sample module."""\n\nstaged_rows = []\n',
    ),
    "todo-format": (
        '"""Sample module."""\n\n# TODO fix this later.\nvalue = 1\n',
        '"""Sample module."""\n\n# TODO: b/1234 - Fix this later.\nvalue = 1\n',
    ),
    "type-comments": (
        '"""Sample module."""\n\nvalue = 1  # type: int\n',
        '"""Sample module."""\n\nvalue: int = 1\n',
    ),
    "tokenization": (
        '"""Sample module."""\n\nvalue = (1\n',
        '"""Sample module."""\n\nvalue = (1,)\n',
    ),
    "class-docstring": (
        '"""Sample module."""\n\n\nclass RowHolder:\n    pass\n',
        '"""Sample module."""\n\n\nclass RowHolder:\n    """Hold rows."""\n',
    ),
    "function-docstring": (
        '"""Sample module."""\n\n\ndef reset():\n    return None\n',
        '''"""Sample module."""


def reset():
    """Reset the state.

    Returns:
        Nothing.
    """
    return None
''',
    ),
    "import-class-not-module": (
        '"""Sample module."""\n\nfrom package import Widget\n\n\nVALUE = Widget()\n',
        '''"""Sample module."""

import package.widgets


VALUE = package.widgets.Widget()
''',
    ),
    "function-length": (
        '''"""Sample module."""


def accumulate():
    """Accumulate a total.

    Returns:
        The total.
    """
    total = 0
    total += 0
    total += 1
    total += 2
    total += 3
    total += 4
    total += 5
    total += 6
    total += 7
    total += 8
    total += 9
    total += 10
    total += 11
    total += 12
    total += 13
    total += 14
    total += 15
    total += 16
    total += 17
    total += 18
    total += 19
    total += 20
    total += 21
    total += 22
    total += 23
    total += 24
    total += 25
    total += 26
    total += 27
    total += 28
    total += 29
    total += 30
    total += 31
    total += 32
    total += 33
    total += 34
    total += 35
    total += 36
    total += 37
    total += 38
    total += 39
    total += 40
    total += 41
    total += 42
    total += 43
    total += 44
    return total
''',
        '''"""Sample module."""


def accumulate():
    """Accumulate a total.

    Returns:
        The total.
    """
    return sum(range(45))
''',
    ),
    "syntax": (
        '"""Sample module."""\n\ndef (:\n',
        '''"""Sample module."""


def reset():
    """Reset the state.

    Returns:
        Nothing.
    """
    return None
''',
    ),
}

# Correct Google-style modules, including the forms that a line-oriented or
# name-oriented checker misreads. Every one of these must audit completely
# clean at violation level.
CLEAN_CORPUS: dict[str, str] = {
    "wrapped_argument_description.py": '''"""Summarize rows for a report."""


def summarize(rows, limit):
    """Summarize rows into a totals report.

    Args:
        rows:
            The rows to summarize, described on the line after the name
            because one line is not enough room for the explanation.
        limit: The largest number of rows to read.

    Returns:
        A mapping of totals keyed by column name.
    """
    return {"rows": rows[:limit]}
''',
    "type_aliases.py": '''"""Bind type aliases in CapWords, as the guide prescribes."""

import collections

OrderedRows = collections.OrderedDict
RowPair = collections.namedtuple("RowPair", "left right")
''',
    "type_comment_inside_a_string.py": '''"""Hold data shaped like a type comment."""

SAMPLE = "value = 1  # type: int"
TODO_SAMPLE = "# TODO fix this"
PYLINT_SAMPLE = "# pylint: disable=invalid-name"
''',
    "wrapped_comment.py": '''"""Carry a comment that wraps over several lines."""

# This comment runs past one line, so the closing period falls on the last
# line of the block rather than on every line of it.
VALUE = 1
''',
    "backslash_inside_a_string.py": '''"""Hold a string ending in a backslash."""

PATTERN = """first line ends with a backslash \\
second line
"""
''',
    "plain_module.py": '''"""Provide a small, entirely conventional module."""


def build_report(rows):
    """Build a report from rows.

    Args:
        rows: The rows to summarize.

    Returns:
        A mapping with the row total.

    Raises:
        ValueError: If rows is empty.
    """
    if not rows:
        raise ValueError("rows is required")
    return {"total": sum(rows)}
''',
}


class RuleMatrixTests(unittest.TestCase):
    """Check every rule against a triggering and a corrected source."""

    def audit(self, source: str) -> list[Any]:
        """Audit one temporary module.

        Args:
            source: Python source text.

        Returns:
            The findings the checker reported.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.py"
            path.write_text(source, encoding="utf-8")
            return CHECKER.audit(path, root)

    def test_every_rule_fires_on_its_triggering_source(self) -> None:
        """Report each rule on a source written to violate it."""
        for rule, (triggering, _) in RULE_CASES.items():
            with self.subTest(rule=rule):
                reported = {finding.rule for finding in self.audit(triggering)}
                self.assertIn(rule, reported)

    def test_no_rule_fires_on_its_corrected_source(self) -> None:
        """Stay silent once the source it objected to is corrected."""
        for rule, (_, corrected) in RULE_CASES.items():
            with self.subTest(rule=rule):
                reported = {finding.rule for finding in self.audit(corrected)}
                self.assertNotIn(rule, reported)

    def test_every_rule_in_the_checker_has_a_case(self) -> None:
        """Fail when a rule is added to the checker without a case here.

        The rule name is the argument before the severity in every add() and
        Finding() call, so the vocabulary can be read straight off the source
        rather than restated by hand and left to drift.
        """
        source = CHECKER_PATH.read_text(encoding="utf-8")
        severities = {"violation", "review"}
        vocabulary = set()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in {"add", "Finding"}:
                continue
            for index, argument in enumerate(node.args):
                if not index or not isinstance(argument, ast.Constant):
                    continue
                if argument.value not in severities:
                    continue
                previous = node.args[index - 1]
                if isinstance(previous, ast.Constant) and isinstance(
                    previous.value, str
                ):
                    vocabulary.add(previous.value)
        self.assertEqual(vocabulary - set(RULE_CASES) - {"source-read"}, set())


class PythonFloorSyntaxTests(unittest.TestCase):
    """Guard the 3.9 floor in the half that does not need a 3.9 interpreter."""

    def test_the_checker_source_carries_no_syntax_newer_than_39(self) -> None:
        """Keep 3.10-and-later syntax out of the checker itself.

        This runs on any interpreter, so the Bazel suite guards it on every
        run. The half that does need a real 3.9 interpreter -- a name such as
        ast.MatchAs that parses everywhere but only exists from 3.10 -- lives
        in test_audit_google_python_style_py39.py and runs in its own CI job.
        """
        source = CHECKER_PATH.read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 9))


class CleanCorpusTests(unittest.TestCase):
    """Hold the checker silent on code that is already correct."""

    def test_correct_modules_report_no_violation(self) -> None:
        """Report nothing at violation level for well-formed modules."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in CLEAN_CORPUS.items():
                (root / name).write_text(source, encoding="utf-8")
            for name in CLEAN_CORPUS:
                with self.subTest(module=name):
                    findings = CHECKER.audit(root / name, root)
                    violations = [
                        f"{finding.rule} at line {finding.line}"
                        for finding in findings
                        if finding.level == "violation"
                    ]
                    self.assertEqual(violations, [])


class SourceReadTests(unittest.TestCase):
    """Cover the one rule a source string cannot express."""

    def test_undecodable_source_is_reported_not_raised(self) -> None:
        """Report a file that is not valid UTF-8 instead of crashing."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "broken.py"
            path.write_bytes(b'"""Sample."""\nvalue = "\xff\xfe"\n')
            findings = CHECKER.audit(path, root)
        self.assertIn("source-read", {finding.rule for finding in findings})


class SelfAuditTests(unittest.TestCase):
    """Hold the companion plugin to the style it exists to enforce."""

    def companion_sources(self) -> list[Path]:
        """Return every Python file shipped in the companion plugin.

        Returns:
            Paths to the plugin's own Python sources.
        """
        companion = ROOT / "plugins/canon-companion"
        return sorted(companion.rglob("*.py"))

    def test_the_companion_plugin_audits_clean(self) -> None:
        """Report no violation against the plugin's own Python sources."""
        companion = ROOT / "plugins/canon-companion"
        sources = self.companion_sources()
        self.assertTrue(sources, "no companion sources were found to audit")
        violations = []
        for path in sources:
            violations.extend(
                f"{finding.file}:{finding.line} {finding.rule}"
                for finding in CHECKER.audit(path, companion)
                if finding.level == "violation"
            )
        self.assertEqual(violations, [])

    def test_auditing_every_repository_source_never_raises(self) -> None:
        """Survive every Python file in the repository without crashing.

        A crasher like the IndexError on a colon-leading Args line aborts the
        whole audit, so breadth matters more here than what is reported.
        """
        sources = sorted(ROOT.rglob("*.py"))
        self.assertGreater(len(sources), 20)
        for path in sources:
            with self.subTest(path=str(path)):
                findings = CHECKER.audit(path, ROOT)
                self.assertNotIn("source-read", {finding.rule for finding in findings})


if __name__ == "__main__":
    unittest.main()
