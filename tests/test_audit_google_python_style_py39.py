"""Hold the companion checker to the repository's Python 3.9 floor.

The checker runs on whatever python3 the developer has, not on a resolved
Bazel toolchain, so it is held to the same 3.9 floor as the hooks. This file
stays free of 3.10-and-later syntax on purpose: CI runs it on a real 3.9
interpreter, where referencing a node type such as ast.MatchAs directly used
to raise AttributeError on every audited file.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = (
    ROOT
    / "plugins/canon-companion/skills/audit-google-python-style/scripts"
    / "check_google_rules.py"
)

SAMPLES = {
    "clean.py": '''"""Summarize rows for a report."""


def build_report(rows):
    """Build a report from rows.

    Args:
        rows:
            The rows to summarize, wrapped onto the following line so the
            continuation handling is exercised here too.

    Returns:
        A mapping with the row total.

    Raises:
        ValueError: If rows is empty.
    """
    if not rows:
        raise ValueError("rows is required")
    return {"total": sum(rows)}
''',
    "dirty.py": '"""Sample module."""\n\nfrom os.path import *\n',
    "comprehensions.py": '''"""Exercise the scope walk without any 3.10 syntax."""

import collections

OrderedRows = collections.OrderedDict
PAIRS = {key: value for key, value in [(1, 2)]}
SQUARES = [value * value for value in range(3)]


def outer(rows):
    """Bind names in several nested scopes.

    Args:
        rows: The rows to walk.

    Returns:
        A list of results.
    """
    try:
        return [row for row in rows if row]
    except TypeError as error:
        return [str(error)]
''',
}


def load_checker():
    """Load the bundled checker from its installed plugin path.

    Returns:
        The imported checker module.
    """
    spec = importlib.util.spec_from_file_location("py39_style_checker", CHECKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Python39FloorTests(unittest.TestCase):
    """Cover what breaks first when the 3.9 floor is not honoured."""

    def test_the_checker_source_parses_under_39(self):
        """Keep 3.10-and-later syntax out of the checker itself."""
        source = CHECKER_PATH.read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 9))

    def test_the_checker_imports_and_audits_without_raising(self):
        """Audit representative sources on whichever interpreter runs this."""
        checker = load_checker()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in SAMPLES.items():
                (root / name).write_text(source, encoding="utf-8")
            reported = {}
            for name in SAMPLES:
                findings = checker.audit(root / name, root)
                reported[name] = {finding.rule for finding in findings}
        self.assertEqual(reported["clean.py"], set())
        self.assertIn("no-wildcard-imports", reported["dirty.py"])
        self.assertEqual(reported["comprehensions.py"], set())

    def test_structural_pattern_node_types_resolve_on_any_version(self):
        """Resolve the 3.10-only match node types without AttributeError."""
        checker = load_checker()
        for name in ("MATCH_NAME_PATTERNS", "MATCH_MAPPING_PATTERNS"):
            patterns = getattr(checker, name)
            self.assertIsInstance(patterns, tuple)
            if sys.version_info < (3, 10):
                self.assertEqual(patterns, ())
            else:
                self.assertTrue(patterns)


if __name__ == "__main__":
    unittest.main()
