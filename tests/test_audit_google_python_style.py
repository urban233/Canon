"""Regression tests for the companion Google Python Style checker."""

from __future__ import annotations

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
    """Load the bundled standalone checker from its installed plugin path."""
    spec = importlib.util.spec_from_file_location("google_style_checker", CHECKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


class GooglePythonStyleCheckerTests(unittest.TestCase):
    """Cover the checker contracts that make the audit skill distinctive."""

    def audit(self, source: str) -> list[Any]:
        """Audit a single temporary Python module."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sample.py"
            path.write_text(source, encoding="utf-8")
            return CHECKER.audit(path, root)

    def test_flags_private_docstrings_imports_and_mutable_defaults(self) -> None:
        """Require violations the evaluation fixture needs the skill to name."""
        findings = self.audit(
            '''"""Sample module."""

from os.path import *


def buildReport(tmp_rows, totals=[]):
    """Build a report.

    Args:
        tmp_rows: Source rows.
        totals: Running totals.
    """
    total = 0; count = 0
    return {"total": total, "count": count, "history": totals}


def _compute_average(total, count):
    return total / count if count else 0.0
'''
        )
        rules = {finding.rule for finding in findings}
        self.assertTrue(
            {
                "no-wildcard-imports",
                "function-naming",
                "tmp-prefix",
                "mutable-default",
                "semicolons",
                "function-docstring",
            }.issubset(rules)
        )

    def test_matches_qualified_raises_and_ignores_nested_scopes(self) -> None:
        """Accept equivalent raises entries without inheriting nested contracts."""
        findings = self.audit(
            '''"""Sample module."""


def qualified() -> None:
    """Raise an error.

    Raises:
        errors.BadError: A bad error.
    """
    raise BadError()


def nested_only() -> None:
    """Run nested code."""
    def inner() -> None:
        """Raise an inner error.

        Raises:
            ValueError: An inner error.
        """
        raise ValueError()
'''
        )
        self.assertNotIn("docstring-raises", [finding.rule for finding in findings])

    def test_flags_confirmed_class_imports_without_guessing_from_case(self) -> None:
        """Require module imports without mistaking PascalCase modules for classes."""
        findings = self.audit(
            '''"""Sample module."""

from package.widgets import Widget
from PySide6 import QtCore
from typing import Any


def build_widget() -> Any:
    """Build a widget.

    Returns:
        A configured widget.
    """
    widget = Widget()
    return QtCore.QObject(widget)
'''
        )
        class_imports = [
            finding for finding in findings if finding.rule == "import-class-not-module"
        ]
        self.assertEqual(len(class_imports), 1)
        self.assertIn("from package import widgets", class_imports[0].message)
        self.assertNotIn("QtCore", class_imports[0].message)

    def test_treats_shadowed_mutable_constructors_as_review_findings(self) -> None:
        """Avoid false violation results when a constructor name is shadowed."""
        findings = self.audit(
            '''"""Sample module."""

list = tuple


def values(items=list()):
    """Return values.

    Args:
        items: Input items.
    """
'''
        )
        mutable_defaults = [
            finding for finding in findings if finding.rule == "mutable-default"
        ]
        self.assertEqual([finding.level for finding in mutable_defaults], ["review"])

    def test_excludes_leading_comments_but_checks_later_comments(self) -> None:
        """Preserve legal headers while reporting ordinary comment violations."""
        findings = self.audit(
            '''# License header without punctuation or `markup`
"""Sample module."""
# Ordinary comment without punctuation
'''
        )
        comment_findings = [
            finding for finding in findings if finding.rule == "comment-punctuation"
        ]
        self.assertEqual([finding.line for finding in comment_findings], [3])


if __name__ == "__main__":
    unittest.main()
