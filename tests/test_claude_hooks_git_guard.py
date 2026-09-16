# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/git_guard.py."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import git_guard


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    _activate(root)


def _activate(root: Path) -> None:
    """Give `root` a verification signal.

    Canon is inert without one (docs/plan.md §07, "No signal, no
    Canon"), so a fixture with no `verify` command exercises the inert
    path rather than the behaviour under test. Every test here that is
    not specifically about going inert calls this.
    """
    config_path = root / ".canon" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"verify": "true"}), encoding="utf-8")


def _invoke_main(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with mock.patch("sys.exit"):
            with mock.patch("sys.stdout", buffer):
                git_guard.main()
    return buffer.getvalue()


def _payload(root: Path, command: str) -> dict[str, Any]:
    return {
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


class DestructiveCommandTests(unittest.TestCase):
    def _assert_denied(self, command: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            self.assertEqual(
                payload["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_force_push_long_flag(self) -> None:
        self._assert_denied("git push --force origin main")

    def test_force_push_short_flag(self) -> None:
        self._assert_denied("git push -f origin main")

    def test_hard_reset(self) -> None:
        self._assert_denied("git reset --hard HEAD~1")

    def test_forced_clean(self) -> None:
        self._assert_denied("git clean -fd")

    def test_forced_clean_flag_order_reversed(self) -> None:
        self._assert_denied("git clean -df")

    def test_local_branch_delete(self) -> None:
        self._assert_denied("git branch -D feature/x")

    def test_remote_branch_delete_via_push(self) -> None:
        self._assert_denied("git push origin --delete feature/x")

    def test_merge(self) -> None:
        self._assert_denied("git merge feature/x")

    def test_merge_with_flags(self) -> None:
        self._assert_denied("git merge --no-ff feature/x")

    def test_remote_branch_delete_via_empty_refspec(self) -> None:
        self._assert_denied("git push origin :feature/x")

    def test_pr_merge(self) -> None:
        self._assert_denied("gh pr merge 42")

    def test_pr_merge_no_args(self) -> None:
        self._assert_denied("gh pr merge")

    def test_pr_merge_squash(self) -> None:
        self._assert_denied("gh pr merge 42 --squash")

    def test_pr_merge_rebase(self) -> None:
        self._assert_denied("gh pr merge 42 --rebase")

    def test_pr_merge_merge_flag(self) -> None:
        self._assert_denied("gh pr merge 42 --merge")

    def test_pr_merge_admin(self) -> None:
        self._assert_denied("gh pr merge 42 --admin")

    def test_pr_merge_auto(self) -> None:
        self._assert_denied("gh pr merge 42 --auto")

    def test_pr_close(self) -> None:
        self._assert_denied("gh pr close 42")

    def test_pr_review_approve_long_flag(self) -> None:
        self._assert_denied("gh pr review 42 --approve")

    def test_pr_review_approve_short_flag(self) -> None:
        self._assert_denied("gh pr review -a")

    def test_pr_review_bare_no_flags(self) -> None:
        """No verdict flag at all: `gh`'s own interactive path to any of
        the three review verdicts, including approval -- see
        git_guard.py's module docstring for why this is denied rather
        than let through."""
        self._assert_denied("gh pr review 42")

    def test_pr_review_bare_survives_a_later_line(self) -> None:
        """`_NON_DELIMITER` treats a newline as a segment boundary, the
        same as `|`/`;`/`&` -- a verdict flag on a later line of a
        multi-line command must not excuse a bare review on an earlier
        one."""
        self._assert_denied("gh pr review 42\ngh pr review 43 --comment -b ok")

    def test_force_push_across_a_line_continuation(self) -> None:
        """A backslash-newline is an ordinary shell line continuation,
        not a segment boundary -- this repo's own eval fixtures write
        multi-line `git` invocations exactly this way. Regression test
        for the newline-segment-boundary fix overshooting onto the
        five §07 patterns it wasn't targeting."""
        self._assert_denied("git push \\\n  --force origin main")

    def test_force_push_quoted_flag_with_no_whitespace(self) -> None:
        """A quoted flag with no whitespace inside it (`"--force"`) is a
        single token the shell hands to `git` with the quotes stripped
        -- indistinguishable from the same flag written bare, and must
        still be denied."""
        self._assert_denied('git push origin "--force"')

    def test_safe_push_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, "git push origin feature/x"))
            self.assertEqual(output, "")

    def test_unrelated_command_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, "git status"))
            self.assertEqual(output, "")

    def test_still_denied_outright_in_pair_mode(self) -> None:
        """Destructive commands are never a question with an answer a
        mode could change -- see git_guard.py's own module docstring."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            config_path = root / ".canon" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps({"verify": "true", "mode": "pair"}), encoding="utf-8"
            )
            output = _invoke_main(_payload(root, "git push --force origin main"))
            payload = json.loads(output)
            self.assertEqual(
                payload["hookSpecificOutput"]["permissionDecision"], "deny"
            )


class NearMissTests(unittest.TestCase):
    """Commands that a looser pattern would deny, and must not.

    Every entry here was denied before this test class existed. A
    `deny` from this hook has no `ask` and no override, so a false
    positive is a command the developer simply cannot run -- worth a
    named regression test each rather than one blanket assertion.
    """

    def _assert_allowed(self, command: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            self.assertEqual(_invoke_main(_payload(root, command)), "")

    def test_merge_base_is_read_only(self) -> None:
        """canon-mcp's own `_git.merge_base` shells out to exactly this."""
        self._assert_allowed("git merge-base HEAD main")

    def test_merge_file_is_not_a_branch_merge(self) -> None:
        self._assert_allowed("git merge-file a.txt base.txt b.txt")

    def test_merge_abort_is_recovery_not_a_merge(self) -> None:
        self._assert_allowed("git merge --abort")

    def test_merge_quit_is_recovery(self) -> None:
        self._assert_allowed("git merge --quit")

    def test_colon_refspec_push_is_an_ordinary_push(self) -> None:
        """Only an *empty* source side deletes; this one creates."""
        self._assert_allowed("git push origin HEAD:refs/heads/feature/x")

    def test_log_merges_is_read_only(self) -> None:
        self._assert_allowed("git log --merges")

    def test_pr_create_is_the_deliverable(self) -> None:
        """docs/plan.md §12: opening a pull request is yes, it IS the
        deliverable -- this must never share a pattern with `pr close`
        or `pr merge`."""
        self._assert_allowed('gh pr create --title x --body "y"')

    def test_pr_view_is_read_only(self) -> None:
        self._assert_allowed("gh pr view 42")

    def test_pr_list_is_read_only(self) -> None:
        self._assert_allowed("gh pr list")

    def test_pr_diff_is_read_only(self) -> None:
        self._assert_allowed("gh pr diff 42")

    def test_pr_checkout_is_not_a_merge(self) -> None:
        self._assert_allowed("gh pr checkout 42")

    def test_pr_status_is_read_only(self) -> None:
        self._assert_allowed("gh pr status")

    def test_pr_comment_is_the_correction_loop(self) -> None:
        """docs/plan.md §12: "Read PR comments, reply to them -- yes."
        `gh pr comment` (a reply) is a different subcommand from `gh pr
        review --comment` (a review verdict) and must stay unblocked."""
        self._assert_allowed('gh pr comment 42 --body "thanks, fixed"')

    def test_pr_review_comment_long_flag(self) -> None:
        self._assert_allowed('gh pr review 42 --comment -b "interesting"')

    def test_pr_review_comment_short_flag(self) -> None:
        self._assert_allowed('gh pr review 42 -c -b "interesting"')

    def test_pr_review_request_changes_long_flag(self) -> None:
        self._assert_allowed('gh pr review 42 --request-changes -b "needs work"')

    def test_pr_review_request_changes_short_flag(self) -> None:
        self._assert_allowed('gh pr review 42 -r -b "needs work"')

    def test_issue_list_is_untouched(self) -> None:
        """§12 permits reading issues; none of the new `gh pr` patterns
        should ever fire on `gh issue ...`."""
        self._assert_allowed("gh issue list")

    def test_issue_close_is_untouched(self) -> None:
        self._assert_allowed("gh issue close 3")

    def test_issue_comment_is_untouched(self) -> None:
        self._assert_allowed('gh issue comment 3 --body "on it"')

    def test_pr_review_help_is_read_only(self) -> None:
        """The very command used to confirm gh's own flag set while
        building this hook must not itself be denied."""
        self._assert_allowed("gh pr review --help")

    def test_pr_review_help_short_flag(self) -> None:
        self._assert_allowed("gh pr review -h")

    def test_merge_abort_quoted_flag_is_still_recovery(self) -> None:
        """`_blank_quoted_spans` only blanks a quoted span that contains
        whitespace -- `"--abort"` has none, so it must still read as
        the recovery flag it is, quoted or not."""
        self._assert_allowed('git merge "--abort"')

    def test_pr_review_comment_quoted_flag_is_still_read_only(self) -> None:
        self._assert_allowed('gh pr review 42 "--comment" -b x')


class QuotedProseTests(unittest.TestCase):
    """A destructive verb mentioned inside a quoted span *that contains
    whitespace* is prose, not the command being run -- `_blank_quoted_
    spans` keeps it from feeding the destructive-pattern check. (A
    quoted span with no whitespace in it is a flag, not prose, and is
    covered separately in `NearMissTests`/`DestructiveCommandTests`.)
    See git_guard.py's module docstring for why.
    """

    def _assert_allowed(self, command: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            self.assertEqual(_invoke_main(_payload(root, command)), "")

    def test_destructive_phrase_in_a_commit_message_is_allowed(self) -> None:
        """This is literally this change's own commit message on this
        branch -- with Canon active, unfixed, it could not have been
        committed."""
        self._assert_allowed(
            'git commit -m "fix: deny gh pr merge/close in the git guard"'
        )

    def test_destructive_phrase_in_a_pr_body_is_allowed(self) -> None:
        self._assert_allowed('gh pr create --title "deny gh pr merge" --body x')

    def test_request_changes_body_mentioning_approve_flag_is_allowed(self) -> None:
        """The body text names `-a` in passing; the actual flag on the
        command is `--request-changes`, which must decide the verdict,
        not a word inside the quotes."""
        self._assert_allowed(
            'gh pr review 42 --request-changes -b "document the -a flag"'
        )

    def test_comment_body_mentioning_approve_flag_is_allowed(self) -> None:
        self._assert_allowed(
            "gh pr review 42 -c -b 'run it with -a next time'"
        )

    def test_force_push_phrase_in_a_commit_message_is_allowed(self) -> None:
        """Pre-existing behaviour change, called out explicitly: before
        quote-blanking, this was denied -- `git push --force` matched
        literally inside the quoted commit message. That was always a
        false positive against a command the developer had every right
        to run; blanking quotes fixes it along with the four new `gh
        pr` patterns."""
        self._assert_allowed("git commit -m \"don't use git push --force\"")

    def test_bash_dash_c_is_the_documented_false_negative(self) -> None:
        """Quote-blanking is a deliberate trade, not an oversight: it
        hides a destructive command from the guard when the whole thing
        is itself inside quotes. Documented in git_guard.py's module
        docstring as an accepted gap -- the guard is a tripwire against
        casual action, not a sandbox."""
        self._assert_allowed('bash -c "gh pr merge 42"')


class InertWithoutVerificationSignalTests(unittest.TestCase):
    """docs/plan.md §07: "Not the gate alone -- the whole plugin."

    See docs/decisions/0001-what-inert-means.md for the two hooks this
    deliberately does not apply to.
    """

    def test_a_destructive_command_is_not_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / ".canon" / "config.json").unlink()
            self.assertEqual(
                _invoke_main(_payload(root, "git push --force origin main")), ""
            )

    def test_an_attribution_trailer_is_not_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / ".canon" / "config.json").unlink()
            command = 'git commit -m "x\n\nCo-Authored-By: A Model <a@b.c>"'
            self.assertEqual(_invoke_main(_payload(root, command)), "")


class AttributionStrippingTests(unittest.TestCase):
    def test_strips_a_co_authored_by_trailer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                "git commit -m \"$(cat <<'EOF'\n"
                "feat: thing\n\n"
                "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
                'EOF\n)"'
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", hook_output["updatedInput"]["command"])
            self.assertIn("feat: thing", hook_output["updatedInput"]["command"])

    def test_commit_without_a_trailer_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(_payload(root, 'git commit -m "fix: thing"'))
            self.assertEqual(output, "")

    def test_strips_trailer_from_a_bash_dash_c_commit(self) -> None:
        """Regression test: the `git commit` detection must run against
        the *original* command, not the quote-blanked one -- the whole
        `bash -c "git commit ..."` argument contains whitespace, so
        blanking would hide the words `git commit` from that check
        entirely and this commit's attribution would reach the repo
        unstripped."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                "bash -c \"git commit -m 'fix: thing\n\n"
                "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
                "done'\""
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", hook_output["updatedInput"]["command"])
            self.assertIn("fix: thing", hook_output["updatedInput"]["command"])


class MiscTests(unittest.TestCase):
    def test_noop_for_unrelated_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(
                {"cwd": str(root), "tool_name": "Read", "tool_input": {}}
            )
            self.assertEqual(output, "")

    def test_noop_when_command_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            output = _invoke_main(
                {"cwd": str(root), "tool_name": "Bash", "tool_input": {}}
            )
            self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
