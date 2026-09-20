# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_git.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from canon_mcp import _git


class RepoRootTests(unittest.TestCase):
    def test_prefers_claude_project_dir_env_var(self) -> None:
        with mock.patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": "/some/repo"}):
            self.assertEqual(_git.repo_root(), Path("/some/repo"))

    def test_falls_back_to_git_when_env_var_missing(self) -> None:
        completed = mock.Mock(returncode=0, stdout="/git/root\n")
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("subprocess.run", return_value=completed):
                self.assertEqual(_git.repo_root(), Path("/git/root"))

    def test_falls_back_to_cwd_when_git_fails(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("subprocess.run", return_value=completed):
                self.assertEqual(_git.repo_root(), Path.cwd())

    def test_falls_back_to_cwd_when_git_is_unreachable(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("subprocess.run", side_effect=OSError("no git")):
                self.assertEqual(_git.repo_root(), Path.cwd())


class GitDerivationTests(unittest.TestCase):
    def test_current_branch_returns_trimmed_output(self) -> None:
        completed = mock.Mock(returncode=0, stdout="feature/widget\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_git.current_branch(Path("/repo")), "feature/widget")

    def test_current_branch_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_git.current_branch(Path("/repo")))

    def test_default_branch_strips_origin_prefix(self) -> None:
        completed = mock.Mock(returncode=0, stdout="origin/develop\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_git.default_branch(Path("/repo")), "develop")

    def test_default_branch_falls_back_to_main(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_git.default_branch(Path("/repo")), "main")

    def test_merge_base_returns_a_short_sha(self) -> None:
        completed = mock.Mock(returncode=0, stdout="abcdef0123456789\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_git.merge_base(Path("/repo"), "main"), "abcdef012")

    def test_merge_base_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=1, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_git.merge_base(Path("/repo"), "main"))

    def test_head_sha_returns_a_short_sha(self) -> None:
        completed = mock.Mock(returncode=0, stdout="0123456789abcdef\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_git.head_sha(Path("/repo")), "012345678")

    def test_head_sha_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_git.head_sha(Path("/repo")))

    def test_full_head_sha_is_not_truncated(self) -> None:
        completed = mock.Mock(returncode=0, stdout="0123456789abcdef\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_git.full_head_sha(Path("/repo")), "0123456789abcdef")

    def test_full_head_sha_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_git.full_head_sha(Path("/repo")))


class IsPushedTests(unittest.TestCase):
    def test_true_when_a_remote_branch_contains_it(self) -> None:
        completed = mock.Mock(returncode=0, stdout="  origin/main\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertTrue(_git.is_pushed(Path("/repo"), "abc1234"))

    def test_false_when_no_remote_branch_contains_it(self) -> None:
        completed = mock.Mock(returncode=0, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertFalse(_git.is_pushed(Path("/repo"), "abc1234"))

    def test_false_when_git_fails(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertFalse(_git.is_pushed(Path("/repo"), "abc1234"))


class CommitsAheadTests(unittest.TestCase):
    def test_returns_the_parsed_count(self) -> None:
        completed = mock.Mock(returncode=0, stdout="3\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(_git.commits_ahead(Path("/repo"), "abc1234"), 3)

    def test_returns_none_when_base_sha_is_none(self) -> None:
        self.assertIsNone(_git.commits_ahead(Path("/repo"), None))

    def test_returns_none_on_non_numeric_output(self) -> None:
        completed = mock.Mock(returncode=0, stdout="not-a-number\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_git.commits_ahead(Path("/repo"), "abc1234"))

    def test_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_git.commits_ahead(Path("/repo"), "abc1234"))


class ChangedPathsTests(unittest.TestCase):
    def test_returns_the_split_lines(self) -> None:
        completed = mock.Mock(returncode=0, stdout="src/a.py\nsrc/b.py\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(
                _git.changed_paths(Path("/repo"), "abc1234"),
                ["src/a.py", "src/b.py"],
            )

    def test_returns_none_on_an_empty_diff(self) -> None:
        completed = mock.Mock(returncode=0, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_git.changed_paths(Path("/repo"), "abc1234"))

    def test_returns_none_on_failure(self) -> None:
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertIsNone(_git.changed_paths(Path("/repo"), "abc1234"))


class AdoptRootsTests(unittest.TestCase):
    """The workspace root an MCP client hands over via `roots/list`.

    This is the only source that works on Antigravity, which substitutes
    no workspace variable into an `mcp_config.json` and spawns the server
    in the *plugin* directory -- so both the env var and `git rev-parse`
    answer about the wrong tree there. See
    docs/decisions/0007-how-canon-mcp-learns-its-workspace-on-antigravity.md.

    The end-to-end half of this -- that a real client's answer actually
    reaches `repo_root()` through the SDK's resolver, and that a client
    which declares no `roots` capability does not make every tool raise
    -- is `tools/check_mcp_roots.py`, which needs `uvx` and cannot run
    hermetically. These cover the parsing and the policy.
    """

    def test_adopts_the_first_usable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adopted = _git.adopt_roots([Path(directory).as_uri()])
            self.assertEqual(adopted, Path(directory))
            self.assertEqual(_git.repo_root(), Path(directory))
        _git.set_client_root(None)

    def test_a_client_root_beats_the_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _git.adopt_roots([Path(directory).as_uri()])
            with mock.patch.dict(
                "os.environ", {"CLAUDE_PROJECT_DIR": "/some/other/repo"}
            ):
                self.assertEqual(_git.repo_root(), Path(directory))
        _git.set_client_root(None)

    def test_skips_a_non_file_scheme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adopted = _git.adopt_roots(
                ["https://example.com/repo", Path(directory).as_uri()]
            )
            self.assertEqual(adopted, Path(directory))
        _git.set_client_root(None)

    def test_skips_a_root_that_is_not_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "nope"
            adopted = _git.adopt_roots([missing.as_uri(), Path(directory).as_uri()])
            self.assertEqual(adopted, Path(directory))
        _git.set_client_root(None)

    def test_decodes_a_percent_encoded_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spaced = Path(directory) / "my repo"
            spaced.mkdir()
            self.assertIn("%20", spaced.as_uri())
            self.assertEqual(_git.adopt_roots([spaced.as_uri()]), spaced)
        _git.set_client_root(None)

    def test_an_empty_answer_clears_a_previous_root(self) -> None:
        # A client that stops offering a workspace must not leave the
        # server answering confidently about a stale one.
        with tempfile.TemporaryDirectory() as directory:
            _git.adopt_roots([Path(directory).as_uri()])
            self.assertIsNotNone(_git.client_root())
            self.assertIsNone(_git.adopt_roots([]))
            self.assertIsNone(_git.client_root())

    def test_an_unusable_answer_leaves_no_root_recorded(self) -> None:
        self.assertIsNone(_git.adopt_roots(["https://example.com/repo"]))
        self.assertIsNone(_git.client_root())


if __name__ == "__main__":
    unittest.main()
