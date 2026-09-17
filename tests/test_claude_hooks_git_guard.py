# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/claude/hooks/git_guard.py."""

from __future__ import annotations

import io
import json
import re
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
        self._assert_allowed("gh pr review 42 -c -b 'run it with -a next time'")

    def test_force_push_phrase_in_a_commit_message_is_allowed(self) -> None:
        """Pre-existing behaviour change, called out explicitly: before
        quote-blanking, this was denied -- `git push --force` matched
        literally inside the quoted commit message. That was always a
        false positive against a command the developer had every right
        to run; blanking quotes fixes it along with the four new `gh
        pr` patterns."""
        self._assert_allowed('git commit -m "don\'t use git push --force"')

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

    def test_trailer_as_last_line_of_double_quoted_message(self) -> None:
        """Issue #58: when the trailer is the last line inside a
        double-quoted `-m` message, the closing quote sits on the same
        regex line as the trailer. The old pattern's `.*` ran to the
        end of that line and took the quote with it, leaving an
        unbalanced command behind."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                'git commit -m "feat: thing\n\n'
                'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"'
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            updated = hook_output["updatedInput"]["command"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", updated)
            self.assertEqual(updated.count('"'), command.count('"'))
            self.assertTrue(updated.endswith('"'))

    def test_trailer_as_last_line_of_single_quoted_message(self) -> None:
        """Same defect, single-quoted form."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                "git commit -m 'feat: thing\n\n"
                "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>'"
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            updated = hook_output["updatedInput"]["command"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", updated)
            self.assertEqual(updated.count("'"), command.count("'"))
            self.assertTrue(updated.endswith("'"))

    def test_trailer_followed_by_further_message_text(self) -> None:
        """A trailer that is not the last line must still be stripped
        cleanly, leaving the text after it intact."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                'git commit -m "feat: thing\n\n'
                "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
                'See-also: something else"'
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            updated = hook_output["updatedInput"]["command"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", updated)
            self.assertIn("See-also: something else", updated)
            self.assertEqual(updated.count('"'), command.count('"'))

    def test_trailer_with_an_apostrophe_in_the_name_is_fully_removed(self) -> None:
        """Repair round 1, finding 1: a trailer whose own text contains
        a quote character (an ordinary thing for a human co-author's
        name to have -- `_TRAILER_LINE` matches any `Co-Authored-By:`
        trailer, not only Claude's) must not leave any readable
        fragment of that text behind. Deleting the whole matched line
        outright would also delete the closing quote sharing it; the
        fix instead keeps only the quote characters the match
        contained, so nothing of "O'Neill" survives -- just the bare
        apostrophe that was part of the command's own quoting."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                'git commit -m "feat: thing\n\n'
                "Co-Authored-By: Mary O'Neill <mary@example.com>\""
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            updated = hook_output["updatedInput"]["command"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", updated)
            self.assertNotIn("O'Neill", updated)
            self.assertNotIn("mary@example.com", updated)
            self.assertEqual(
                git_guard._QUOTE_CHAR.findall(command),
                git_guard._QUOTE_CHAR.findall(updated),
            )

    def test_trailer_with_a_double_quote_in_the_name_is_fully_removed(self) -> None:
        """Same defect, with the trailer's own quote character matching
        the type used to enclose the `-m` message rather than the
        other type."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            command = (
                "git commit -m 'feat: thing\n\n"
                'Co-Authored-By: "Ada" Lovelace <ada@example.com>\''
            )
            output = _invoke_main(_payload(root, command))
            payload = json.loads(output)
            hook_output = payload["hookSpecificOutput"]
            updated = hook_output["updatedInput"]["command"]
            self.assertEqual(hook_output["permissionDecision"], "allow")
            self.assertNotIn("Co-Authored-By", updated)
            self.assertNotIn("Ada", updated)
            self.assertNotIn("Lovelace", updated)
            self.assertNotIn("ada@example.com", updated)
            self.assertEqual(
                git_guard._QUOTE_CHAR.findall(command),
                git_guard._QUOTE_CHAR.findall(updated),
            )


class TrailerQuoteParityTests(unittest.TestCase):
    """`_strip_attribution` must never change the *subsequence* of quote
    characters in the command it rewrites -- see its docstring in
    git_guard.py, and issue #58, for why. That is stronger than equal
    counts: it means no `"` or `'` can appear to move from inside a
    quoted region to outside it (or vice versa), which is what rules
    out the fix injecting anything. This is the property the fix has to
    hold; the specific cases in `AttributionStrippingTests` are
    examples of it, not a substitute for it. Three of the commands
    below contain no quote character inside the trailer text and are
    byte-identical before and after the fix -- kept as pins against a
    future change, but by themselves they exercise nothing that a
    no-op rewrite wouldn't also satisfy; the two with a quote character
    inside the trailer are what actually exercises this property.

    This property is necessary but not sufficient for the rewritten
    command to still parse: repair round 2 found a case where the
    subsequence was provably intact and the command was still broken
    (a glued-on quote character defeated a heredoc terminator, which
    depends on line position, not on quote characters at all). See
    `HeredocTerminatorTests` below for that case, which this class
    cannot catch by construction."""

    _COMMANDS = [
        # Double-quoted, trailer is the last line. No quote inside the
        # trailer text: a pin, not a stress case.
        (
            'git commit -m "feat: thing\n\n'
            'Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"'
        ),
        # Single-quoted, trailer is the last line. Same pin, other
        # quote type.
        (
            "git commit -m 'feat: thing\n\n"
            "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>'"
        ),
        # Trailer followed by further message text. Also a pin.
        (
            'git commit -m "feat: thing\n\n'
            "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
            'See-also: something else"'
        ),
        # The heredoc form, which must keep working exactly as it does
        # today -- it proves nothing about the fix on its own, but the
        # invariant must hold for it too. Also a pin.
        (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: thing\n\n"
            "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
            'EOF\n)"'
        ),
        # bash -c wrapping a single-quoted commit message. Also a pin.
        (
            "bash -c \"git commit -m 'fix: thing\n\n"
            "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
            "done'\""
        ),
        # An apostrophe inside the trailer's own name, double-quoted
        # message -- the actual stress case for finding 1.
        (
            'git commit -m "feat: thing\n\n'
            "Co-Authored-By: Mary O'Neill <mary@example.com>\""
        ),
        # A double quote inside the trailer's own name, single-quoted
        # message -- same stress case, other quote type.
        (
            "git commit -m 'feat: thing\n\n"
            'Co-Authored-By: "Ada" Lovelace <ada@example.com>\''
        ),
    ]

    def test_quote_subsequence_is_unchanged_for_every_rewritten_command(self) -> None:
        for command in self._COMMANDS:
            with self.subTest(command=command):
                stripped = git_guard._strip_attribution(command)
                self.assertIsNotNone(stripped)
                assert stripped is not None
                self.assertEqual(
                    git_guard._QUOTE_CHAR.findall(command),
                    git_guard._QUOTE_CHAR.findall(stripped),
                )


class HeredocTerminatorTests(unittest.TestCase):
    """Repair round 2, finding B1. A heredoc terminator (`EOF` in this
    repo's own commit style) has to be alone on its line to close the
    heredoc -- that is a property of a line's *position*, not of which
    quote characters it contains, so no quote-parity or quote-subsequence
    assertion can see a rewrite that breaks it. Round 1's fix kept a
    trailer's own quote character but glued it onto the *front* of the
    following line -- if that following line was a heredoc terminator,
    the result was `'EOF` instead of `EOF`, which never matches the
    terminator and leaves the heredoc, and the whole command, unclosed.
    The subsequence was provably still intact; the command still didn't
    parse.

    These tests assert on the rewritten command's *shape* -- that the
    terminator line is exactly `EOF`, alone -- rather than shelling out
    to `bash -n`, deliberately, even though `bash -n` is what actually
    answers "does this parse" and is how this defect was first
    confirmed. Doing that as an automated, CI-gated test turned out to
    depend on which `bash` happens to be first on `PATH`: this repo's
    interactive shell resolves a modern one (5.x), but Bazel's sandboxed
    test run resolves macOS's ancient system `/bin/bash` (3.2), which
    has its own, unrelated defect -- it can mis-lex a `<<'quoted'`
    heredoc whenever the heredoc body is not quote-*balanced* when read
    as ordinary shell text, because its single-pass lexer still tracks
    quote balance through heredoc bodies that should be opaque to it. A
    trailer carrying a single apostrophe in a name is the common way to
    get there, so this fix's output -- correct under the invariants it's
    required to hold -- still fails `bash -n` on that one shell. The
    unrewritten command fails there too: the rewrite preserves the quote
    subsequence, which is what that shell keys on, so it cannot flip the
    verdict either way. That is a real, separate finding, reported
    rather than chased: see `_strip_attribution`'s own docstring in
    git_guard.py for the full note. A shape assertion tests the actual
    contract this fix controls (the terminator's position) without
    being hostage to which bash binary happens to be resolved when the
    suite runs."""

    def _assert_terminator_alone(self, command: str, terminator: str) -> None:
        self.assertRegex(
            command,
            rf"(?m)^{re.escape(terminator)}$",
            msg=f"heredoc terminator {terminator!r} is not alone on its own "
            f"line in:\n{command}",
        )

    def test_heredoc_with_an_apostrophe_in_the_trailer_still_closes(self) -> None:
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: thing\n\n"
            "Co-Authored-By: Mary O'Neill <mary@example.com>\n"
            'EOF\n)"'
        )
        stripped = git_guard._strip_attribution(command)
        self.assertIsNotNone(stripped)
        assert stripped is not None
        self.assertNotIn("Co-Authored-By", stripped)
        self._assert_terminator_alone(stripped, "EOF")

    def test_heredoc_with_a_double_quote_in_the_trailer_still_closes(self) -> None:
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: thing\n\n"
            'Co-Authored-By: "Ada" Lovelace <ada@example.com>\n'
            'EOF\n)"'
        )
        stripped = git_guard._strip_attribution(command)
        self.assertIsNotNone(stripped)
        assert stripped is not None
        self.assertNotIn("Co-Authored-By", stripped)
        self._assert_terminator_alone(stripped, "EOF")

    def test_quote_free_heredoc_is_still_byte_identical(self) -> None:
        """The `quotes and` guard in `_rewrite` is load-bearing: without
        it, a quote-free trailer would also gain a spurious blank line
        where the trailer used to be. Pinned here as its own test
        because `test_strips_a_co_authored_by_trailer` only checks
        substrings, not the exact text."""
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: thing\n\n"
            "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
            'EOF\n)"'
        )
        expected = "git commit -m \"$(cat <<'EOF'\nfeat: thing\n\nEOF\n)\""
        self.assertEqual(git_guard._strip_attribution(command), expected)


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
