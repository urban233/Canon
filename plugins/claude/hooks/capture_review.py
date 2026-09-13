# SPDX-License-Identifier: BSD-3-Clause
"""Canon's `SubagentStop` hook -- captures a reviewer's own verdict.

Matched in hooks.json to both `"canon:reviewer"` and
`"canon:risk-reviewer"` (Claude Code's hooks reference documents
plugin-scoped `SubagentStop` matchers, e.g. `^my-plugin:reviewer$`).
Mirrors `save_plan.py`'s tolerant style: trust the matcher, but bail if
a payload field that IS present clearly disagrees with it, rather than
acting on some other subagent's output. Logs under the actual
`agent_type` (falling back to `"reviewer"` only when that field is
absent) rather than a hardcoded name, so a `risk-reviewer` verdict lands
under its own key in `.canon/hooks/decisions.jsonl` -- exactly what
`review.py`'s `last_decision(root, "risk-reviewer")` looks up.

Reads `last_assistant_message` directly -- Claude Code's own hooks
reference says to use this field, not `transcript_path`, for exactly
this purpose on `Stop`/`SubagentStop` events. This is the mechanism
that makes Invariant III real: the verdict comes from the reviewer's
own final message, never from the main session's retelling of it.

Writes through the existing `.canon/hooks/decisions.jsonl` log (see
`_common.log_decision`) rather than a new storage mechanism -- that
file is already documented as read-for-display-only, which is exactly
`canon_review`'s job.
"""

from __future__ import annotations

import _common

_DECISIONS = (
    "READY FOR HUMAN APPROVAL",
    "CHANGES REQUIRED",
    "BLOCKED BY MISSING EVIDENCE",
)
_ALLOWED_AGENT_TYPES = ("reviewer", "risk-reviewer")
_REASON_PREVIEW_CHARS = 200


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
    agent_type = payload.get("agent_type")
    if agent_type not in (None, *_ALLOWED_AGENT_TYPES):
        return
    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return
    decision = _extract_decision(message)
    if decision is None:
        return

    root = _common.repo_root(payload)
    reason = message.strip()[:_REASON_PREVIEW_CHARS]
    _common.log_decision(
        root,
        agent_type or "reviewer",
        decision,
        reason=reason,
        extra={"head": _common.head_sha(root)},
    )


if __name__ == "__main__":
    _common.fail_open(main)()
