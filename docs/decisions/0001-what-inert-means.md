# 0001. What "inert" excludes

## Context

`docs/plan.md` §07 states the precondition without qualification:

> If no command can be established, Canon **stays inert** rather than
> running without it. Not the gate alone — the whole plugin.

Taken literally this is every hook, including the one that asks the
first-run question. Until this change only `stop.py` honoured the
precondition at all: `plan_gate.py`, `check_scope.py`, `git_guard.py`
and `capture_review.py` never loaded the config, so installing Canon in
a repository with no `.canon/config.json` gated the first edit and
denied `git merge` — the opposite of inert.

Implementing §07 literally is impossible as written. `stop.py`'s
block is the only mechanism that puts the first-run question in front of
a developer. If it goes inert too, nothing ever asks, `.canon/config.json`
is never written, and Canon is permanently inert in every repository that
installs it — the plugin would have no path out of its own precondition.

A second case is not impossible but is hostile. `session_start.py` only
ever injects `additionalContext`; it gates nothing. Silencing it makes an
inert Canon indistinguishable from a broken or uninstalled one, which is
precisely the state §07's own "declining is not blocking" paragraph
wants to be legible.

## Decision

Everything that gates, guards or captures goes inert with no
verification signal, through a named predicate `_config.canon_is_active`:
`plan_gate.py`, `check_scope.py`, `git_guard.py`, `capture_review.py`.

Two hooks stay live:

- **`stop.py`** — its first-run block is the bootstrap, and the only
  route to a configured repository. It still runs no verification while
  unconfigured; it only asks.
- **`session_start.py`** — pure context, never a gate. Its
  `Verify: not configured yet` line is how a developer learns Canon is
  inert rather than broken.

`capture_review.py` is grouped with the gates rather than with
`session_start.py` despite being passive, because the verdict it captures
is exactly what `canon_ship` gates on. Capturing while inert accumulates
evidence for a check that must not run.

The MCP tools are unaffected. They are pull-based — the agent asks, they
answer — so they are not gates in the sense §07 means, and
`canon_position` already reports `verify_configured: false` with a
`next_step` pointing at first-run setup. Making them inert would remove
the clearest report of *why* Canon is inert.

## Consequences

Installing Canon in an unconfigured repository now changes nothing about
how the session behaves except that one `Stop` asks one question, and
`SessionStart` says where things stand. That is what §07 promised and
what the code did not do.

The rejected alternative — inert meaning literally every hook — loses on
being unimplementable rather than on taste: it removes the only path to
configuration. The narrower rejected alternative, keeping
`capture_review.py` live because it merely writes a gitignored
diagnostic, loses because `canon_review` reads that file back and
`canon_ship` gates on the result, so "merely diagnostic" is not true of
this particular record.

The cost is that "the whole plugin" in §07 is now two named exceptions
wide, and a reader of the plan alone would not predict them. That is the
reason this record exists; the plan document is not edited to match.
