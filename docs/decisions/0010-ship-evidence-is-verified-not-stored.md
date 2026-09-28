# 0010. Ship evidence is verified, not stored

## Context

§08 answers "is this branch green?" in exactly two ways: CI, for a
pushed commit, and a fresh local re-run of the `verify` command, for
one that isn't. "Why there is no evidence store" argues that nothing
else is needed. The `Stop` hook's answer is consumed inside the hook,
CI's is already keyed by the SHA, and §15 records the question as
settled: "Canon stores nothing." §07 sends the slow half of a
repository's checks to CI, as "a different layer with different
authority".

A field report from `open-protein-platform`
(`docs/field-reports/2026-09-28-open-protein-platform-movie-export.md`)
hit the case that split leaves out. The step's real evidence was a
7-minute display-bound run, a Swift suite, a Python suite and about 40
mutants. The agent's account is that none of it can run in CI, because
it needs a display. It is also far too slow to be the `verify` command
the `Stop` hook runs every turn. So the configured `verify` was ruff, and
`canon_ship`'s "evidence green at this HEAD" rested on ruff alone. The
evidence that mattered reached Canon nowhere. The agent carried it by
hand in prompts and in the PR body. The project's own `evidence.json`
recorded no commit, and a reviewer matched it to HEAD by its timestamp.

That last detail is the failure this record is about. A timestamp match
is plausible, and it can be wrong: evidence produced before an amend,
or on a dirty tree, looks identical to evidence for HEAD. §07's
principle, "wrong-but-plausible is worse than absent", applies to
evidence as much as to the verify command.

§08's own rule expected a case like this: "Canon may cache only a pure
function of an immutable input, and only when recomputing costs more
than the cache risks. Nothing currently qualifies on the second
clause." A 7-minute run that CI cannot perform is the first thing to
qualify.

## Decision

**Canon verifies ship evidence the repository produces, and stores none
of its own.**

A repository may declare one ship-evidence result in
`.canon/config.json`:

```json
{
  "verify": "just lint",
  "ship_evidence": {
    "command": "just evidence",
    "result": "build/canon-evidence.json"
  }
}
```

Canon never runs `command`. It is there so Canon can tell the agent and
the developer what to run. `result` is a path the repository gitignores.
The project's own command writes it, in this shape:

```json
{"tree": "<git tree SHA of HEAD when the run started>",
 "dirty": false,
 "passed": true,
 "checks": [{"name": "evidence run", "passed": true}]}
```

`canon_evidence` reports it next to the existing CI and local-rerun
answer. `canon_ship`, when `ship_evidence` is declared, is ready only if
the file exists, `dirty` is false, `passed` is true, and `tree` equals
`git rev-parse HEAD^{tree}`. Anything else is a named reason in
`missing` that says what to run: the file is absent, malformed, stale or
dirty. Without the key, behaviour is unchanged.

Four properties make this consistent with §08, not a reversal of it:

- **Canon writes nothing.** The repository's command writes the file.
  Canon reads it and checks it. The invariant that Canon writes no
  repository state holds, and the `Stop` counter stays its one
  exception.
- **The binding is checked, never trusted.** A tree SHA names an
  immutable input, so the result can go missing but cannot silently
  describe the wrong code. That is the property §08 granted the SHA memo
  it rejected. The objection there was that Canon would hold a second
  copy of what CI already knows, and that does not apply to evidence CI
  cannot produce.
- **Keyed by tree, not commit.** A rebase or an amend that changes no
  content keeps its evidence. Any content change, including docs-only,
  invalidates it.
- **The two existing answers are untouched.** CI still answers for a
  pushed commit, and the `verify` command still answers for the `Stop`
  hook. Ship evidence is a third answer, and only for the question those
  two cannot reach.

## Alternatives rejected

- **A Canon-owned cache, even outside the repository.** It would be a
  second exception to the invariant, and Canon would be holding a copy
  of the truth. That is the CoDev shape §08 exists to refuse.
- **Having `canon_ship` re-run the slow suites itself.** This is
  closest to §08's "the honest answer is a fresh local re-run". But a
  7-minute display-bound run does not fit inside one MCP tool call, and
  Canon's own verify timeout is 300 seconds. It would also re-run the
  whole suite on every `canon_ship` call after a stale review.
- **The status quo**, where evidence is carried in prose and matched by
  timestamp. The field report shows this already produces a guess.

## Consequences

- **This verifies the binding, not the honesty.** An agent could write
  the result file by hand. That is no weaker than the prose it replaces,
  and the file is something a reviewer can read in one place instead of
  scratchpad paths. Detecting a hand-written file is out of scope.
- **Mutation evidence is not part of this record.** "Each check fails
  against its defect" is a claim about the tests, not about whether HEAD
  is green. `checks` can carry it later, but that needs its own argument.
- **The plan document is not edited.** A reader of §08's table or §15's
  "Where does evidence live between turns?" will find two answers where
  there are now three. This record is where that reader is meant to
  land, as with `0003`, `0005` and `0006`.
- **One field report is the whole evidence base.** The claim that CI
  cannot run the evidence is the reporting agent's, not independently
  checked. If a second repository never needs this key, the key costs
  nothing. If none ever does, it should be removed.
