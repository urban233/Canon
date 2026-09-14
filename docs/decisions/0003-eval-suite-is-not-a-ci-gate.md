# 0003. The eval suite is a local tool, not a CI gate

## Context

`docs/plan.md` §14 is explicit about Phase 3: "Build the `claude plugin
eval` suite, then delete instructions until something fails... Publish
the suite with the plugin so the next model generation can re-run it.
Deliberately last, and deliberately not optional... **Gate on it in
CI.**"

Every `claude plugin eval` run starts a real, billed model call — the
suite's own docs put it plainly: "Every eval run and every judge grader
is a real model call on your account, counted against your plan's usage
or your API bill." Gating CI on it means every pull request needs
`ANTHROPIC_API_KEY` (or equivalent) available to the runner, and every
push spends real money on top of the deterministic `bazel test` suite
CI already runs for free.

This is not a new question for this repository. The Phase 0–2
gap-closure series (`.canon/plans/features/phase-0-2-gap-closure.md`,
step 9) withdrew a different test for exactly this reason: a real
headless `claude -p` run asserting `async` mode's behavior, because "a
test that needs an API key in CI is not suited to Canon at its current
stage." That withdrawal was scoped to one test; this decision is the
same reasoning applied to the mechanism §14 asks to gate the entire
build on.

## Decision

The eval suite is a **local, on-demand developer tool** — run with
`just eval` — and is never wired into `ci` or any GitHub Actions
workflow. `.canon/config.json`'s own `verify` command, and everything
`just ci` already runs, are unaffected.

This is a direct deviation from §14's literal instruction, made
consciously rather than by omission. Two things distinguish gating on a
deterministic test suite from gating on this one:

- **Cost and credentials are structural, not incidental.** A flaky
  network call or a slow integration test is a tractable CI problem;
  a job that cannot run at all without a funded API key is a different
  kind of dependency for a repository anyone should be able to clone,
  build, and verify without first acquiring model access.
- **The suite's purpose is ablation, not regression-catching on every
  push.** §14 frames it as the tool that answers "does this
  instruction still earn its place" — a question asked when trimming
  or changing a skill/agent/hook's prose, not on every unrelated
  commit. A local run before and after an instruction change is the
  right cadence for that question; a CI gate would run it on commits
  that never touch an instruction at all.

## Consequences

A regression in how reliably a skill or agent steers the model can land
on `main` without CI catching it, until someone runs `just eval` by
hand. That is a real, accepted gap relative to what §14 asks for, and
it is why this record exists rather than a silent read of "gate on it
in CI" as aspirational.

The mitigation is discipline rather than mechanism: `just eval` runs
before and after any change to a skill, agent, or hook's instruction
text, and its `report.html` is the evidence that a deletion in the
ablation pass (the next unit) didn't cost anything measurable. If
Canon's own usage ever funds a CI credential as a matter of course, or
a lighter-weight subset of the suite (deterministic graders only, still
a real model call but a cheaper one) turns out to be worth gating on,
that is a new decision with its own record — this one does not
foreclose it, and the plan document is not edited to match it.
