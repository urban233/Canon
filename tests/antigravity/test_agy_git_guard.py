# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity/hooks/git_guard.py."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tests.antigravity.conftest import (
    create_test_git_repo,
    invoke_hook_main,
    load_agy_module,
    make_pre_tool_payload,
)

agy_git_guard = load_agy_module("git_guard")
agy_config = load_agy_module("_config")
agy_common = load_agy_module("_common_agy")


class GitGuardDestructiveOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def _assert_denied(self, command: str, expected_label: str) -> None:
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": command},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "deny")
        self.assertIn("Canon never runs", parsed.get("reason", ""))
        self.assertIn(expected_label, parsed.get("reason", ""))

    def test_blocks_force_push_variants(self) -> None:
        self._assert_denied("git push --force origin main", "a force push")
        self._assert_denied("git push -f origin feat", "a force push")
        self._assert_denied("git push origin --force", "a force push")

    def test_blocks_hard_reset_variants(self) -> None:
        self._assert_denied("git reset --hard", "a hard reset")
        self._assert_denied("git reset --hard HEAD~1", "a hard reset")
        self._assert_denied("git reset HEAD~2 --hard", "a hard reset")

    def test_blocks_forced_clean_variants(self) -> None:
        self._assert_denied(
            "git clean -fd", "a forced clean of untracked files/directories"
        )
        self._assert_denied(
            "git clean -f -d", "a forced clean of untracked files/directories"
        )
        self._assert_denied(
            "git clean --force --directory",
            "a forced clean of untracked files/directories",
        )
        self._assert_denied(
            "git clean -df", "a forced clean of untracked files/directories"
        )

    def test_blocks_branch_deletion_variants(self) -> None:
        self._assert_denied("git branch -D old-branch", "a branch deletion")
        self._assert_denied("git branch --delete old-branch", "a branch deletion")

    def test_blocks_remote_branch_deletion_variants(self) -> None:
        self._assert_denied(
            "git push origin --delete old-branch", "a remote branch deletion"
        )
        self._assert_denied("git push origin :old-branch", "a remote branch deletion")

    def test_blocks_merge_variants(self) -> None:
        self._assert_denied("git merge main", "a merge")
        self._assert_denied("git merge feat/login", "a merge")
        self._assert_denied("git merge --no-ff dev", "a merge")


class GitGuardAllowedOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def _assert_allowed(self, command: str) -> None:
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": command},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})

    def test_allows_merge_base(self) -> None:
        self._assert_allowed("git merge-base HEAD origin/main")
        self._assert_allowed("git merge-base --is-ancestor main HEAD")

    def test_allows_merge_abort_and_recovery(self) -> None:
        self._assert_allowed("git merge --abort")
        self._assert_allowed("git merge --quit")
        self._assert_allowed("git merge --continue")

    def test_allows_regular_push(self) -> None:
        self._assert_allowed("git push origin HEAD:refs/heads/feature-x")
        self._assert_allowed("git push origin feature-x")

    def test_allows_soft_or_mixed_reset(self) -> None:
        self._assert_allowed("git reset --soft HEAD~1")
        self._assert_allowed("git reset HEAD~1")

    def test_allows_benign_commands(self) -> None:
        self._assert_allowed("git status")
        self._assert_allowed("git log -n 5")
        self._assert_allowed("git diff HEAD~1")


class GitGuardAttributionStrippingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_strips_single_co_authored_by_trailer(self) -> None:
        cmd = (
            'git commit -m "Add feature\n\n'
            'Co-Authored-By: Claude <claude@anthropic.com>"'
        )
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": cmd},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "allow")
        overwrite = parsed.get("overwrite")
        self.assertIsNotNone(overwrite)
        assert overwrite is not None
        new_cmd = overwrite.get("CommandLine")
        self.assertNotIn("Co-Authored-By", new_cmd)
        self.assertIn('git commit -m "Add feature', new_cmd)

    def test_strips_multiple_trailers(self) -> None:
        cmd = (
            'git commit -m "Fix bug\n\n'
            "Co-Authored-By: Claude Bot <bot@anthropic.com>\n"
            'Co-Authored-By: Other <other@example.com>"'
        )
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": cmd},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "allow")
        new_cmd = parsed["overwrite"]["CommandLine"]
        self.assertNotIn("Co-Authored-By", new_cmd)

    def test_clean_commit_preserved_without_overwrite(self) -> None:
        cmd = 'git commit -m "Clean commit without trailers"'
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": cmd},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})
        self.assertNotIn("overwrite", parsed)


class GitGuardInertWhenUnconfiguredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        # Unconfigured repo: no .canon/config.json

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_destructive_commands_allowed_when_unconfigured(self) -> None:
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": "git reset --hard HEAD~1"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})

    def test_commits_with_trailers_allowed_without_overwrite_when_unconfigured(
        self,
    ) -> None:
        cmd = 'git commit -m "Message\n\nCo-Authored-By: Claude <c@example.com>"'
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": cmd},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertEqual(parsed, {"decision": "allow"})
        self.assertNotIn("overwrite", parsed)


class GitGuardPrCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def _assert_denied(self, command: str, expected_label: str) -> None:
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": command},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "deny")
        self.assertIn(f"Canon never runs {expected_label}", parsed.get("reason", ""))

    def _assert_allowed(self, command: str) -> None:
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": command},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("decision"), "allow")

    def test_blocks_gh_pr_merge(self) -> None:
        self._assert_denied("gh pr merge 42 --squash", "a pull request merge")
        self._assert_denied("gh pr merge --auto --rebase", "a pull request merge")
        self._assert_denied("gh pr merge", "a pull request merge")

    def test_blocks_gh_pr_close(self) -> None:
        self._assert_denied("gh pr close 42", "a pull request close")
        self._assert_denied("gh pr close 42 --delete-branch", "a pull request close")

    def test_blocks_gh_pr_review_approve(self) -> None:
        msg = "an approving pull request review"
        self._assert_denied("gh pr review 42 --approve", msg)
        self._assert_denied("gh pr review 42 -a", msg)

    def test_blocks_bare_gh_pr_review(self) -> None:
        msg = (
            "a pull request review with no verdict flag "
            "(name --comment or --request-changes instead)"
        )
        self._assert_denied("gh pr review 42", msg)

    def test_allows_gh_pr_create(self) -> None:
        self._assert_allowed('gh pr create --title "feat" --body "details"')

    def test_allows_gh_pr_view_and_comment(self) -> None:
        self._assert_allowed("gh pr view 42")
        self._assert_allowed("gh pr view 42 --json statusCheckRollup")
        self._assert_allowed('gh pr comment 42 --body "LGTM"')
        self._assert_allowed('gh pr review 42 --comment --body "Looks good"')
        self._assert_allowed('gh pr review 42 --request-changes --body "Fix tests"')

    def test_allows_gh_pr_review_help(self) -> None:
        self._assert_allowed("gh pr review --help")
        self._assert_allowed("gh pr review -h")


class GitGuardQuotedSpanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = create_test_git_repo()
        self.artifacts = Path(tempfile.mkdtemp(prefix="canon_artifacts_"))
        agy_config.save_config(self.repo, {"verify": "pytest"})

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.artifacts, ignore_errors=True)

    def test_commit_message_mentioning_gh_pr_merge_allowed(self) -> None:
        cmd = 'git commit -m "fix: resolve gh pr merge conflict in pipeline"'
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": cmd},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertEqual(parsed.get("decision"), "allow")

    def test_quoted_flags_without_whitespace_still_denied(self) -> None:
        payload1 = make_pre_tool_payload(
            "run_command",
            {"CommandLine": "git branch '-D' feat-old"},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed1, _, _ = invoke_hook_main(agy_git_guard, payload=payload1)
        self.assertEqual(parsed1.get("decision"), "deny")
        self.assertIn("a branch deletion", parsed1.get("reason", ""))

        payload2 = make_pre_tool_payload(
            "run_command",
            {"CommandLine": 'git push "--force" origin main'},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed2, _, _ = invoke_hook_main(agy_git_guard, payload=payload2)
        self.assertEqual(parsed2.get("decision"), "deny")
        self.assertIn("a force push", parsed2.get("reason", ""))

    def test_quote_preserving_trailer_stripping(self) -> None:
        cmd = (
            'git commit -m "Feature message\n\n'
            "Co-Authored-By: Mary O'Neill <mary@example.com>\n"
            'Co-Authored-By: Claude <claude@anthropic.com>"'
        )
        payload = make_pre_tool_payload(
            "run_command",
            {"CommandLine": cmd},
            workspace=self.repo,
            artifact_dir=self.artifacts,
        )
        parsed, _, _ = invoke_hook_main(agy_git_guard, payload=payload)
        self.assertEqual(parsed.get("decision"), "allow")
        self.assertIn("overwrite", parsed)
        new_cmd = parsed["overwrite"]["CommandLine"]
        self.assertNotIn("Co-Authored-By", new_cmd)
        # Quotes should remain balanced
        self.assertEqual(new_cmd.count('"'), 2)


if __name__ == "__main__":
    unittest.main()
