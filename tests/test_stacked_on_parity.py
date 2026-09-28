# SPDX-License-Identifier: BSD-3-Clause
"""Tests for `stacked_on` and the fork-point `merge_base`, run against
both copies: `plan_header` (src/canon_hooks, the save side) and
`canon_mcp._stack` (the read side), which deliberately share no
dependency edge -- see `_stack.py`'s module docstring. Every case asserts
the two agree, so the duplication cannot drift silently.

The regression behind this: a field session on a stacked feature saw
every step's `base` pinned to the stack root, and a SessionStart diff of
326 files against `main` for one step's change.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import _common
import plan_header

from canon_mcp import _git, _stack


def _git_run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _commit(root: Path, message: str) -> None:
    _git_run(
        root,
        "-c",
        "user.email=canon@example.com",
        "-c",
        "user.name=Canon Tests",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        message,
    )


def _repo(root: Path) -> None:
    _git_run(root, "init", "-q")
    _git_run(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _commit(root, "init")


def _parent_step(root: Path) -> None:
    """`a`, one step ahead of `main`."""
    _git_run(root, "switch", "-q", "-c", "a")
    _commit(root, "step a")


def _both(root: Path, branch: str) -> str | None:
    """`stacked_on` from both copies, asserted equal."""
    hooks = plan_header.stacked_on(root, branch)
    mcp = _stack.stacked_on(root, branch)
    if hooks != mcp:
        raise AssertionError(f"copies disagree: hooks={hooks!r} mcp={mcp!r}")
    return hooks


def _write_plan(root: Path, branch: str, stacked: str) -> None:
    path = plan_header.branch_plan_path(root, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\nstatus: approved\nstacked_on: "{stacked}"\n---\n\n# Plan\n',
        encoding="utf-8",
    )


class StackedOnTests(unittest.TestCase):
    def test_switch_c_from_a_parent_step(self) -> None:
        """`git switch -c b` logs "Created from HEAD"; the HEAD reflog's
        "moving from a to b" names the parent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _parent_step(root)
            _git_run(root, "switch", "-q", "-c", "b")
            _commit(root, "step b")
            self.assertEqual(_both(root, "b"), "a")
            self.assertEqual(plan_header.base_ref(root, "b"), "a")
            self.assertEqual(_stack.base_ref(root, "b"), "a")

    def test_branch_created_from_a_named_start_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _parent_step(root)
            _git_run(root, "branch", "b", "a")
            _git_run(root, "switch", "-q", "b")
            self.assertEqual(_both(root, "b"), "a")

    def test_a_branch_cut_from_the_default_is_not_stacked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _git_run(root, "switch", "-q", "-c", "b")
            _commit(root, "step b")
            self.assertIsNone(_both(root, "b"))
            self.assertEqual(plan_header.base_ref(root, "b"), "main")

    def test_a_parent_with_nothing_beyond_the_default_is_not_a_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _git_run(root, "switch", "-q", "-c", "a")
            _git_run(root, "switch", "-q", "-c", "b")
            _commit(root, "step b")
            self.assertIsNone(_both(root, "b"))

    def test_a_deleted_parent_falls_back_to_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _parent_step(root)
            _git_run(root, "switch", "-q", "-c", "b")
            _git_run(root, "branch", "-q", "-D", "a")
            self.assertIsNone(_both(root, "b"))

    def test_the_header_answers_when_the_reflog_cannot(self) -> None:
        """A branch fetched on another machine has no "Created from"."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _parent_step(root)
            _git_run(root, "switch", "-q", "-c", "b")
            _commit(root, "step b")
            _git_run(root, "reflog", "expire", "--expire=now", "--all")
            self.assertIsNone(_both(root, "b"))
            _write_plan(root, "b", "a")
            self.assertEqual(_both(root, "b"), "a")

    def test_the_header_naming_the_default_means_not_stacked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _parent_step(root)
            _git_run(root, "switch", "-q", "-c", "b")
            _write_plan(root, "b", "main")
            self.assertIsNone(_both(root, "b"))

    def test_a_squash_merged_parent_left_behind_is_not_a_parent(self) -> None:
        """Regression: `a` squash-merged into `main` and still checked
        out locally, `b` moved onto `main`. `a`'s fork point is now older
        than `main`'s, so measuring from it would widen every range."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _parent_step(root)
            _git_run(root, "switch", "-q", "-c", "b")
            _commit(root, "step b")
            _git_run(root, "switch", "-q", "main")
            _commit(root, "step a, squashed")
            _git_run(root, "switch", "-q", "b")
            _git_run(root, "reset", "-q", "--hard", "main")
            _commit(root, "step b, moved onto main")
            self.assertIsNone(_both(root, "b"))
            _write_plan(root, "b", "a")
            self.assertIsNone(_both(root, "b"))

    def test_the_default_branch_is_never_stacked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            self.assertIsNone(_both(root, "main"))


class MergeBaseTests(unittest.TestCase):
    def test_a_stale_local_default_is_measured_from_its_remote(self) -> None:
        """Regression: `base` was measured from the local default branch,
        so a checkout whose `main` lagged `origin/main` reported every
        commit merged since as part of the branch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            _git_run(root, "switch", "-q", "-c", "upstream")
            _commit(root, "merged upstream since")
            fork = _git_run(root, "rev-parse", "HEAD")
            _git_run(root, "update-ref", "refs/remotes/origin/main", fork)
            _git_run(root, "switch", "-q", "-c", "work")
            _commit(root, "work")
            self.assertEqual(_common.merge_base(root, "main"), fork[:9])
            self.assertEqual(_git.merge_base(root, "main"), fork[:9])

    def test_only_the_local_ref_when_there_is_no_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            init = _git_run(root, "rev-parse", "HEAD")
            _git_run(root, "switch", "-q", "-c", "work")
            _commit(root, "work")
            self.assertEqual(_common.merge_base(root, "main"), init[:9])
            self.assertEqual(_git.merge_base(root, "main"), init[:9])

    def test_none_for_a_ref_that_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _repo(root)
            self.assertIsNone(_common.merge_base(root, "nope"))
            self.assertIsNone(_git.merge_base(root, "nope"))


if __name__ == "__main__":
    unittest.main()
