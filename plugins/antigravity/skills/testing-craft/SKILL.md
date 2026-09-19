---
name: testing-craft
description: Provides Google-derived testing strategy, test-writing craft, and test-suite health reference, distilled from Software Engineering at Google (the Flamingo book), the Google Testing Blog, and Google's published testing-infrastructure research. Canon's `reviewer` subagent reads the writing-craft and strategy references as review criteria. Invoke directly to design a test strategy, audit an existing suite's health, or triage a flaky or brittle test.
---

# Testing Craft

Reference for designing a test strategy, writing individual tests well,
and keeping a test suite healthy over time -- distilled from Google's
public testing methodology (*Software Engineering at Google*, the Google
Testing Blog, and Google's peer-reviewed testing-infrastructure research).
This skill has no template of its own; it sharpens test content another
skill or agent is already producing.

## Invocation boundary

Use this skill in two situations:

- **As a prerequisite.** Canon's `reviewer` subagent reads
  `references/writing-tests.md` and `references/test-strategy.md` as its
  review criteria for a change's tests. That's a read, not a full
  invocation of this skill -- continue in the calling agent's own
  workflow.
- **Directly**, when the developer asks to design a test strategy for a
  change, audit an existing test suite's health, triage a specific flaky
  or brittle test, or invokes `$testing-craft`.

## Apply the references

- `references/test-strategy.md` -- size vs. scope, the target test-count
  pyramid and its antipatterns, when a larger test earns its cost, and the
  coverage-decision heuristic. Read before deciding *what* to test and at
  what level.
- `references/writing-tests.md` -- DAMP over DRY for test code, behavior-
  named tests, the test-doubles priority ladder, and the brittleness
  checklist. Read before writing or revising an individual test.
- `references/test-suite-health.md` -- hermetic tests, flaky-test triage,
  and coverage-as-diagnostic. Read before auditing or maintaining an
  existing suite.

Each reference ends in a numbered self-check; run it against the test
content before treating that content as done.

## When invoked directly

1. Identify which of three cases applies: a new or revised test strategy,
   a health audit of an existing suite, or triage of one specific flaky or
   brittle test. Ask if the developer's request is ambiguous between them
   -- the three use different references and produce different output.
2. **New or revised strategy.** Gather the change's actual risk and shape
   (new component, size, blast radius, existing coverage) from the
   developer's request and the repository itself. Apply
   `references/test-strategy.md` to produce a size/scope recommendation, a
   test-doubles approach, and a list of any larger tests that earn their
   cost -- with the reasoning, not just the list. Hand the result back
   into the calling skill's own artifact if one is open; otherwise present
   it directly.
3. **Suite health audit.** Inspect the existing suite's structure, runtime,
   and recent CI or test-run history if available. Apply
   `references/test-suite-health.md`'s checklist (hermeticity, flake
   signal, pyramid shape) and `references/writing-tests.md`'s brittleness
   signals. Report findings ranked by how much trust they erode, each with
   specific evidence (a flaky test's failure history, a brittle test's
   coupling to an internal method) -- do not silently rewrite tests as
   part of an audit; that is separate, explicitly-requested work once the
   developer accepts a finding.
4. **Flaky or brittle triage.** Apply `references/test-suite-health.md`'s
   triage decision tree to the specific test named. Recommend one of
   fix-now, quarantine-and-ticket, or delete, with the reasoning, not a
   default.

## Handoff

This skill does not decide product scope, architecture, or which change
to make -- it only sharpens test content already in scope. Return control
to the calling skill or the developer once the relevant self-check passes,
or once a direct invocation's findings are reported.
