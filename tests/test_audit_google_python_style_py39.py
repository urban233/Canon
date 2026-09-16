"""Hold the companion checker to the repository's Python 3.9 floor.

The checker runs on whatever python3 the developer has, not on a resolved
Bazel toolchain, so it is held to the same 3.9 floor as the hooks. This file
stays free of 3.10-and-later syntax on purpose.

Run it with `just test-py39` on a real 3.9 interpreter, which is what the
python39-floor CI job does. It is deliberately NOT a Bazel test target: Bazel
pins a hermetic 3.13 (see MODULE.bazel), so a green Bazel run would say
nothing about the floor while looking exactly like proof of it. The tests
that depend on the interpreter skip rather than pass when it is not 3.9, so
running this on 3.13 by hand cannot be misread either.

The version-independent half of this check -- that no 3.10-and-later syntax
reaches the checker at all -- lives in test_audit_google_python_style_rules.py
instead, so the Bazel suite still guards it on every run.
"""

from __future__ import annotations

import importlib.util
import os
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


ON_THE_FLOOR = sys.version_info[:2] == (3, 9)
NOT_ON_THE_FLOOR = (
    "needs a real 3.9 interpreter; this ran on "
    + ".".join(str(part) for part in sys.version_info[:3])
    + " -- run `just test-py39` with 3.9 on PATH"
)


@unittest.skipUnless(ON_THE_FLOOR, NOT_ON_THE_FLOOR)
class Python39FloorTests(unittest.TestCase):
    """Cover what breaks first when the 3.9 floor is not honoured.

    Skipped wholesale off 3.9. Passing these on 3.13 would prove nothing
    about the floor, and a silent pass is what let a 3.10-only attribute
    reference reach review in the first place.
    """

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

    def test_structural_pattern_node_types_resolve_to_nothing(self):
        """Resolve the 3.10-only match node types without AttributeError.

        On 3.9 these names do not exist, so the checker must resolve them to
        an empty tuple: every isinstance check against it is then false,
        which is correct because a match statement cannot parse here at all.
        """
        checker = load_checker()
        for name in ("MATCH_NAME_PATTERNS", "MATCH_MAPPING_PATTERNS"):
            patterns = getattr(checker, name)
            self.assertIsInstance(patterns, tuple)
            self.assertEqual(patterns, ())


class FloorEnforcementTests(unittest.TestCase):
    """Refuse to let the floor check pass by skipping."""

    def test_the_interpreter_is_39_where_the_floor_is_required(self):
        """Fail, rather than skip, in a job that exists to check the floor.

        Skipping is the right answer for a developer without 3.9 installed.
        It is the wrong answer for the python39-floor CI job, which would
        otherwise report green having verified nothing -- the same silent
        pass this whole file exists to prevent. That job sets
        CANON_REQUIRE_PY39, which turns the skip into a failure.
        """
        if not os.environ.get("CANON_REQUIRE_PY39"):
            self.skipTest("set CANON_REQUIRE_PY39=1 to require 3.9 here")
        self.assertTrue(ON_THE_FLOOR, NOT_ON_THE_FLOOR)


if __name__ == "__main__":
    unittest.main()
