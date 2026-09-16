"""Regression tests for the companion Google Python Style checker."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
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

    def test_allows_private_pascal_case_and_rejects_lowercase_classes(self) -> None:
        """Preserve private class names while rejecting invalid class casing."""
        findings = self.audit(
            '''"""Sample module."""


class _Private:
    """Private class."""


class privateClass:
    """Lowercase class."""
'''
        )
        class_findings = [
            finding for finding in findings if finding.rule == "class-naming"
        ]
        self.assertEqual(len(class_findings), 1)
        self.assertEqual(class_findings[0].level, "violation")

    def test_callable_raise_requires_one_complete_exception_entry(self) -> None:
        """Require precise documentation for dynamically generated exceptions."""
        source = '''"""Sample module."""


def generated():
    """Generate an error."""
    raise make_error()
'''
        findings = self.audit(source)
        self.assertIn("docstring-raises", [finding.rule for finding in findings])

        valid = source.replace(
            '    """Generate an error."""',
            '''    """Generate an error.

    Raises:
        Exception: A generated error.
    """''',
        )
        self.assertNotIn(
            "docstring-raises", [finding.rule for finding in self.audit(valid)]
        )

        wrong = valid.replace(
            "Exception: A generated error.", "ValueError: A generated error."
        )
        self.assertIn(
            "docstring-raises", [finding.rule for finding in self.audit(wrong)]
        )

        invalid_entries = (
            "Exception: A generated error.\n        ValueError: An extra error.",
            "Exception:",
            "Exception: A generated error",
        )
        for entry in invalid_entries:
            with self.subTest(entry=entry):
                invalid = source.replace(
                    '    """Generate an error."""',
                    f'''    """Generate an error.

    Raises:
        {entry}
    """''',
                )
                self.assertTrue(
                    any(finding.level == "violation" for finding in self.audit(invalid))
                )

    def test_rejects_each_known_mutable_default_form(self) -> None:
        """Reject mutable literals, comprehensions, and built-in constructors."""
        findings = self.audit(
            '''"""Sample module."""


def invalid_defaults(
    items=[],
    mapping={},
    names=set(),
    generated=[item for item in ()],
    *,
    options=dict(),
):
    """Use invalid defaults.

    Args:
        items: Item values.
        mapping: Mapped values.
        names: Name values.
        generated: Generated values.
        options: Option values.
    """


async def valid_defaults(value=None, values=(), *, names=frozenset()):
    """Use immutable defaults.

    Args:
        value: Optional value.
        values: Immutable values.
        names: Immutable names.
    """
'''
        )
        mutable_defaults = [
            finding for finding in findings if finding.rule == "mutable-default"
        ]
        self.assertEqual(len(mutable_defaults), 5)
        self.assertTrue(
            all(finding.level == "violation" for finding in mutable_defaults)
        )

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

    def test_comprehension_scopes_distinguish_local_and_enclosing_bindings(
        self,
    ) -> None:
        """Keep local targets out of, and named expressions in, enclosing scope."""
        findings = self.audit(
            '''"""Sample module."""


def local_target(values):
    """Bind a comprehension-local name.

    Args:
        values: Source values.
    """
    observed = [value for list in values for value in list]

    def still_builtin(items=list()):
        """Use an unshadowed constructor.

        Args:
            items: Item values.
        """


def enclosing_binding(values):
    """Bind a name in the containing scope.

    Args:
        values: Source values.
    """
    observed = [(list := tuple) for value in values]

    def shadowed(items=list()):
        """Use a shadowed constructor.

        Args:
            items: Item values.
        """
'''
        )
        mutable_defaults = [
            finding for finding in findings if finding.rule == "mutable-default"
        ]
        self.assertEqual(
            [finding.level for finding in mutable_defaults],
            ["violation", "review"],
        )

    def test_definition_time_binding_shadows_later_default(self) -> None:
        """Resolve default expressions in their containing lexical scope."""
        findings = self.audit(
            '''"""Sample module."""


def binder(first=(list := tuple), second=list()):
    """Bind a constructor while evaluating defaults.

    Args:
        first: First default value.
        second: Second default value.
    """
'''
        )
        mutable_defaults = [
            finding for finding in findings if finding.rule == "mutable-default"
        ]
        self.assertEqual(len(mutable_defaults), 1)
        self.assertEqual(mutable_defaults[0].level, "review")

    def test_pattern_captures_shadow_mutable_constructors(self) -> None:
        """Collect match-as, match-star, and mapping-rest bindings."""
        findings = self.audit(
            '''"""Sample module."""


def capture_names(value):
    """Capture a direct name.

    Args:
        value: Value to match.
    """
    match value:
        case list:
            pass

    def match_as(items=list()):
        """Use a match-as-shadowed constructor.

        Args:
            items: Item values.
        """


def capture_sequences(value):
    """Capture a sequence name.

    Args:
        value: Value to match.
    """
    match value:
        case [*dict]:
            pass

    def match_star(mapping=dict()):
        """Use a match-star-shadowed constructor.

        Args:
            mapping: Mapped values.
        """


def capture_mappings(value):
    """Capture a mapping-rest name.

    Args:
        value: Value to match.
    """
    match value:
        case {**set}:
            pass

    def match_mapping(names=set()):
        """Use a match-mapping-shadowed constructor.

        Args:
            names: Name values.
        """
'''
        )
        mutable_defaults = [
            finding for finding in findings if finding.rule == "mutable-default"
        ]
        self.assertEqual(len(mutable_defaults), 3)
        self.assertTrue(all(finding.level == "review" for finding in mutable_defaults))

    @unittest.skipIf(sys.version_info < (3, 12), "PEP 695 requires Python 3.12")
    def test_type_parameters_shadow_mutable_constructors(self) -> None:
        """Collect generic function and class type parameters as bindings."""
        findings = self.audit(
            '''"""Sample module."""


def outer[list]():
    """Define a generic function."""

    def inner(items=list()):
        """Use a function-type-parameter-shadowed constructor.

        Args:
            items: Item values.
        """


class Container[dict]:
    """Define a generic class."""

    def inner(self, mapping=dict()):
        """Use a class-type-parameter-shadowed constructor.

        Args:
            mapping: Mapped values.
        """
'''
        )
        mutable_defaults = [
            finding for finding in findings if finding.rule == "mutable-default"
        ]
        self.assertEqual(len(mutable_defaults), 2)
        self.assertTrue(all(finding.level == "review" for finding in mutable_defaults))

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

    def test_colon_leading_section_line_does_not_abort_the_audit(self) -> None:
        """Survive a reST parameter line inside a Google Args section."""
        findings = self.audit(
            '''"""Sample module."""


def summarize(rows):
    """Summarize rows.

    Args:
        :param rows: Source rows.

    Returns:
        A summary.
    """
    return rows
'''
        )
        self.assertIn("docstring-args", {finding.rule for finding in findings})

    def test_star_args_entries_still_satisfy_required_parameters(self) -> None:
        """Keep matching starred Args entries to their parameter names."""
        findings = self.audit(
            '''"""Sample module."""


def summarize(rows, *extras, **options):
    """Summarize rows.

    Args:
        rows: Source rows.
        *extras: Extra rows.
        **options: Extra options.

    Returns:
        A summary.
    """
    return rows, extras, options
'''
        )
        self.assertEqual(
            [finding for finding in findings if finding.rule == "docstring-args"], []
        )

    def test_pattern_node_types_resolve_without_python_310(self) -> None:
        """Hold the checker to the repository's 3.9 floor for match nodes.

        Structural pattern matching node types do not exist before 3.10, so
        referencing them directly raised AttributeError on every audited file.
        """
        self.assertEqual(
            CHECKER.MATCH_NAME_PATTERNS,
            tuple(
                node_type
                for node_type in (
                    getattr(ast, "MatchAs", None),
                    getattr(ast, "MatchStar", None),
                )
                if node_type is not None
            ),
        )
        self.assertEqual(
            CHECKER.MATCH_MAPPING_PATTERNS,
            tuple(
                node_type
                for node_type in (getattr(ast, "MatchMapping", None),)
                if node_type is not None
            ),
        )


class GooglePythonStyleCliTests(unittest.TestCase):
    """Cover the command line contract Phase A depends on."""

    def run_checker(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run the checker as a subprocess and capture its result."""
        return subprocess.run(
            [sys.executable, str(CHECKER_PATH), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_root_is_a_usage_error_rather_than_a_clean_audit(self) -> None:
        """Reject a root that does not exist."""
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent"
            result = self.run_checker("--root", str(missing))
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not exist", result.stderr)

    def test_file_root_is_a_usage_error_rather_than_a_clean_audit(self) -> None:
        """Reject a root that points at a file instead of a directory."""
        result = self.run_checker("--root", str(CHECKER_PATH))
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be a directory", result.stderr)

    def test_root_without_python_files_is_a_usage_error(self) -> None:
        """Reject a root that holds nothing the checker can audit."""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "notes.txt").write_text("text", encoding="utf-8")
            result = self.run_checker("--root", directory)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no Python files", result.stderr)

    def test_clean_root_exits_zero_and_violations_exit_one(self) -> None:
        """Preserve the pass and fail statuses Phase B loops on."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text('"""Sample module."""\n', encoding="utf-8")
            clean = self.run_checker("--root", directory)
            path.write_text("value = 1\n", encoding="utf-8")
            dirty = self.run_checker("--root", directory)
        self.assertEqual(clean.returncode, 0)
        self.assertEqual(dirty.returncode, 1)
        self.assertIn("module-docstring", dirty.stdout)


if __name__ == "__main__":
    unittest.main()
