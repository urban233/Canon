# Canon

Canon is an agentic-development plugin (Claude Code, Codex and
Antigravity), not a
general application -- its own implementation follows the same design it
ships to others.

**The plan artifact is the specification.** Read it before proposing any
change to Canon's design:
https://claude.ai/code/artifact/1453894c-9e0b-40fe-b661-d5f0e53eca5f
(rendered at `docs/plan.md`). Canon is built to that document and to CoDev's
recorded experience, not discovered by using the tool -- do not treat using
Canon as a substitute for reading it.

Preserve these invariants, all argued for in the plan artifact:

- Position is derived from git, GitHub, and the plan file -- never stored.
- Canon writes no repository state of its own, with one narrow exception:
  a `Stop` hook's consecutive-refusal counter, which lives in session-scoped
  state outside the repository, never inside it.
- Every gate fails open. A guardrail that errors must never block work.
- Canon never authors a commit of its own, and never merges or closes a
  pull request.

`just` is the entry point (`just --list`). Run it for every code change.

This file stays small on purpose -- an instruction line earns its place
through an eval that fails without it (see the plan artifact, §13), not by
accumulation. It is expected to stay near this length even as Canon grows.
