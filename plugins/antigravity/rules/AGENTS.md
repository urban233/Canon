# Canon

Canon keeps agentic development on track without a stored state machine.
These rules apply while the Canon plugin is enabled.

Antigravity merges a plugin's `rules/` into the active rule set for **the
project you are working in**, so this file says only what is true there.
Canon's own development instructions live in this repository's root
`AGENTS.md` and are deliberately not shipped here.

## Invariants

- Position is derived from git, GitHub, and the plan file -- never stored.
- Canon writes no repository state of its own, with one narrow exception:
  a `Stop` hook's consecutive-refusal counter, which lives in the session's
  own artifact directory, never in the repository.
- Every gate fails open. A guardrail that errors must never block work.
- Canon never authors a commit of its own, and never merges or closes a
  pull request.
- Nothing ships on the agent's own word: progress is gated by verified
  command exit codes and independent reviewer verdicts, never unverified
  assertions.

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
