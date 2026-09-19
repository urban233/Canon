# Canon

Canon is an Antigravity plugin, not a general application -- its own
implementation follows the same design it ships to others.

**The plan artifact is the specification.** Read it before proposing any
change to Canon's design:
https://claude.ai/code/artifact/1453894c-9e0b-40fe-b661-d5f0e53eca5f
(rendered at `docs/plan.md`). Canon is built to that document and to CoDev's
recorded experience, not discovered by using the tool -- do not treat using
Canon as a substitute for reading it.

## Invariants

Preserve these invariants, all argued for in the plan artifact:

- Position is derived from git, GitHub, and the plan file -- never stored.
- Canon writes no repository state of its own, with one narrow exception:
  a `Stop` hook's consecutive-refusal counter, which lives in the session's
  scratchpad directory (`artifactDirectoryPath / conversationId / canon`),
  never in the repository.
- Every gate fails open. A guardrail that errors must never block work.
- Canon never authors a commit of its own, and never merges or closes a pull request.
- Nothing ships on the agent's own word: progress is gated by verified command
  exit codes and independent reviewer verdicts, never unverified assertions.

just is the entry point (`just --list`). Run it for every code change.

## Authorship

Never add yourself as an author, co-author, or contributor to anything in
this repository.

- No `Co-Authored-By:` trailer, and no other trailer naming an AI tool,
  model, session, or vendor, on any commit.
- No "Generated with", "Created by", "Written by AI", or similar line in a
  pull request body, issue, commit message, changelog entry, or any file.
- Never add an AI tool or model to `AUTHORS`, `CONTRIBUTORS`, `CITATION.cff`,
  package or dataset metadata, a file header, or a docstring byline.
- Never sign, initial, or otherwise mark generated prose as your own work.

The author of a change is the person who asked for it and who takes
responsibility for it. Attribute the work to them and to no one else. If
you believe a change genuinely needs an attribution note, say so and let
them decide -- do not add one.

---

This file stays small on purpose -- an instruction line earns its place
through an eval that fails without it (see the plan artifact, §13), not by
accumulation. It is expected to stay near this length even as Canon grows.
