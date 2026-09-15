# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `SubagentStop` hook -- captures a reviewer's own verdict.

Bound in each platform's own hooks manifest to whatever matcher that
platform's `SubagentStop` supports for the `reviewer` and `risk-reviewer`
subagents (Claude Code documents a plugin-scoped form, e.g.
`^my-plugin:reviewer$`). This module doesn't hardcode a matcher itself --
it trusts the binding, but bails if a payload field that IS present
clearly disagrees with it, rather than acting on some other subagent's
output. Logs under a normalized key (`"reviewer"` or `"risk-reviewer"`)
rather than whatever exact, possibly-namespaced string the platform
reports, so a `risk-reviewer` verdict always lands under that key in
`.canon/hooks/decisions.jsonl` -- exactly what `review.py`'s
`last_decision(root, "risk-reviewer")` looks up, regardless of platform.

Reads `last_assistant_message` directly -- both supported platforms'
hooks references say to use this field, not `transcript_path`, for
exactly this purpose on `Stop`/`SubagentStop` events (confirmed directly
for both, not just documented). This is the mechanism that makes
Invariant III real: the verdict comes from the reviewer's own final
message, never from the main session's retelling of it.

Writes through the existing `.canon/hooks/decisions.jsonl` log (see
`_common.log_decision`) rather than a new storage mechanism -- that
file is already documented as read-for-display-only, which is exactly
`canon_review`'s job.

Inert without a verification signal (docs/plan.md §07, "No signal, no
Canon"): with no `verify` command in `.canon/config.json` this hook is a
silent no-op. See docs/decisions/0001-what-inert-means.md for why
`stop.py` and `session_start.py` are the two exceptions.
"""

from __future__ import annotations

import _common
import _config

_DECISIONS = (
    "READY FOR HUMAN APPROVAL",
    "CHANGES REQUIRED",
    "BLOCKED BY MISSING EVIDENCE",
)
_REASON_PREVIEW_CHARS = 200


def _match_known_agent(agent_type: str | None) -> str | None:
    """The canonical logging key for `agent_type` (`"reviewer"` or
    `"risk-reviewer"`), or None if it clearly isn't either of Canon's two
    reviewer subagents.

    Matched by substring rather than exact equality: a platform may
    report a namespaced form (Claude Code's own `SubagentStop` matcher
    pattern is `<plugin>:reviewer`, and the exact value Codex reports for
    a custom subagent was not possible to confirm empirically -- see
    docs/codex-hook-surface.md), so an exact-equality check would
    silently stop capturing verdicts on a platform that namespaces the
    name. `"risk-reviewer"` is checked first because it contains
    `"reviewer"` as a substring. A missing `agent_type` altogether is
    treated as the plain reviewer, matching this hook's original,
    narrower-payload behaviour.
    """
    if agent_type is None:
        return "reviewer"
    if "risk-reviewer" in agent_type:
        return "risk-reviewer"
    if "reviewer" in agent_type:
        return "reviewer"
    return None


def _extract_decision(message: str) -> str | None:
    """Whichever of the three literal decision strings appears last in
    `message`, or None if none appear.

    `review-change` instructs the reviewer to end with exactly one of
    these; taking the last occurrence is a defensive tie-break in case
    an earlier one is quoted or discussed en route to it.
    """
    best_index = -1
    best_decision: str | None = None
    for decision in _DECISIONS:
        index = message.rfind(decision)
        if index > best_index:
            best_index = index
            best_decision = decision
    return best_decision


def main() -> None:
    payload = _common.read_payload()
    if payload is None:
        return
    raw_agent_type = payload.get("agent_type")
    agent_key = _match_known_agent(
        raw_agent_type if isinstance(raw_agent_type, str) else None
    )
    if agent_key is None:
        return
    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return
    decision = _extract_decision(message)
    if decision is None:
        return

    root = _common.repo_root(payload)
    if not _config.canon_is_active(_config.load_config(root)):
        # Inert: this verdict is what `canon_ship` gates on, so capturing
        # it here would accumulate evidence for a check that must not run.
        return
    reason = message.strip()[:_REASON_PREVIEW_CHARS]
    _common.log_decision(
        root,
        agent_key,
        decision,
        reason=reason,
        extra={"head": _common.head_sha(root)},
    )


if __name__ == "__main__":
    _common.fail_open(main)()
