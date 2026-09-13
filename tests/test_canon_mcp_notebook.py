# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_notebook.py.

docs/plan.md §07's three notebook commitments, at the primitive level:
extract code-cell source, count *cells* changed rather than lines, and
notice whether the repository already provides a readable form.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from canon_mcp import _notebook


def _nb(*cells: tuple[str, object]) -> str:
    """A minimal but real nbformat document.

    `source` is written as a list of lines -- the shape Jupyter itself
    writes -- rather than the string shape, so the tests exercise the
    form that actually appears on disk.
    """
    return json.dumps(
        {
            "cells": [
                {
                    "cell_type": kind,
                    "source": source,
                    "execution_count": 7,
                    "outputs": [{"text": "noise"}],
                    "metadata": {},
                }
                for kind, source in cells
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )


class CodeCellSourceTests(unittest.TestCase):
    def test_extracts_only_code_cells(self) -> None:
        text = _nb(("markdown", ["# Title\n"]), ("code", ["x = 1\n"]))
        self.assertEqual(_notebook.code_cell_sources(text), ["x = 1\n"])

    def test_accepts_a_string_source(self) -> None:
        text = _nb(("code", "x = 1\n"))
        self.assertEqual(_notebook.code_cell_sources(text), ["x = 1\n"])

    def test_joins_a_list_source(self) -> None:
        text = _nb(("code", ["x = 1\n", "y = 2\n"]))
        self.assertEqual(_notebook.code_cell_sources(text), ["x = 1\ny = 2\n"])

    def test_unparsable_notebook_is_none(self) -> None:
        self.assertIsNone(_notebook.code_cell_sources("not json at all"))

    def test_json_that_is_not_a_notebook_is_none(self) -> None:
        self.assertIsNone(_notebook.code_cell_sources('["a", "b"]'))


class ChangedCodeCellTests(unittest.TestCase):
    def test_output_churn_alone_is_zero_cells_changed(self) -> None:
        """The whole point of §07's rule. A notebook re-run with no code
        edit rewrites execution_count and outputs; lines changed says
        "large", code cells changed says "nothing happened"."""
        before = _nb(("code", ["x = 1\n"]))
        after = json.loads(before)
        after["cells"][0]["execution_count"] = 99
        after["cells"][0]["outputs"] = [{"text": "completely different" * 200}]
        self.assertEqual(_notebook.changed_code_cells(before, json.dumps(after)), 0)

    def test_one_edited_cell_counts_as_one(self) -> None:
        before = _nb(("code", ["x = 1\n"]), ("code", ["y = 2\n"]))
        after = _nb(("code", ["x = 42\n"]), ("code", ["y = 2\n"]))
        self.assertEqual(_notebook.changed_code_cells(before, after), 1)

    def test_an_added_cell_counts(self) -> None:
        before = _nb(("code", ["x = 1\n"]))
        after = _nb(("code", ["x = 1\n"]), ("code", ["y = 2\n"]))
        self.assertEqual(_notebook.changed_code_cells(before, after), 1)

    def test_markdown_edits_do_not_count(self) -> None:
        before = _nb(("markdown", ["# A\n"]), ("code", ["x = 1\n"]))
        after = _nb(("markdown", ["# Completely new\n"]), ("code", ["x = 1\n"]))
        self.assertEqual(_notebook.changed_code_cells(before, after), 0)

    def test_a_new_notebook_counts_every_cell(self) -> None:
        after = _nb(("code", ["x = 1\n"]), ("code", ["y = 2\n"]))
        self.assertEqual(_notebook.changed_code_cells(None, after), 2)

    def test_unparsable_is_none_not_zero(self) -> None:
        """ "I can't tell" must never read as "nothing changed"."""
        self.assertIsNone(_notebook.changed_code_cells("{}", "garbage"))


class PairedScriptTests(unittest.TestCase):
    def test_finds_a_sibling_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "analysis.ipynb").write_text(_nb(), encoding="utf-8")
            (root / "analysis.py").write_text("# %%\n", encoding="utf-8")
            self.assertEqual(
                _notebook.paired_script(root, "analysis.ipynb"), "analysis.py"
            )

    def test_none_when_unpaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_notebook.paired_script(Path(tmp), "analysis.ipynb"))


class ReadableFormConfiguredTests(unittest.TestCase):
    def test_nbstripout_filter_in_gitattributes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitattributes").write_text(
                "*.ipynb filter=nbstripout\n", encoding="utf-8"
            )
            self.assertTrue(_notebook.has_readable_form_configured(root))

    def test_jupytext_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "jupytext.toml").write_text("", encoding="utf-8")
            self.assertTrue(_notebook.has_readable_form_configured(root))

    def test_jupytext_in_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[tool.jupytext]\nformats = 'ipynb,py'\n", encoding="utf-8"
            )
            self.assertTrue(_notebook.has_readable_form_configured(root))

    def test_nothing_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_notebook.has_readable_form_configured(Path(tmp)))

    def test_an_unrelated_gitattributes_line_does_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitattributes").write_text("*.png binary\n", encoding="utf-8")
            self.assertFalse(_notebook.has_readable_form_configured(root))


class IsNotebookTests(unittest.TestCase):
    def test_recognises_the_suffix(self) -> None:
        self.assertTrue(_notebook.is_notebook("notebooks/Analysis.IPYNB"))
        self.assertFalse(_notebook.is_notebook("src/thing.py"))


if __name__ == "__main__":
    unittest.main()
