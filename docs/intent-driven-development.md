# Intent-driven development

*How to state intent and verify outcomes — and what that means for a
project whose output isn't deterministic*

> This document explains the method Canon serves. `docs/plan.md` §13 states
> it in two sentences; this is the long form, written for an engineer who
> knows trunk-based development well and is new to working this way.
>
> The worked example throughout is a **PyMOL Copilot** — an agent that
> helps structural biologists drive PyMOL. It is not a Canon component; it
> is a concrete second project to reason about, deliberately chosen
> because it is model-backed and therefore exercises the hardest part of
> the method.

---

## 01 · The sentence everything else follows from

`docs/plan.md` §13 puts it this way:

> The developer's job moves to *stating intent and reviewing outcomes*,
> roughly inverting the old 90/10 split between writing and reviewing.
> The saved plan is the artifact that makes intent explicit and
> reviewable; the reviewer subagent and the `Stop` hook are what make
> reviewing outcomes tractable at that volume. **The leverage is in
> specifying and verifying, not in choreographing the steps in between.**

Two halves, and neither survives alone. Intent without verification is
taking the agent's word for it. Verification without intent is a test
suite with no product behind it. Everything below is a consequence of
holding both.

The middle — choreographing the steps — is the part that used to be the
job and is now the part to leave alone. `docs/plan.md` §13 again:
"Over-specifying steps is the documented primary failure mode, and
experienced engineers do it most."

---

## 02 · Two different things are called "planning"

You will hear that AI-assisted teams have stopped planning. That is a bad
summary of something true. Two practices share the word, and only one of
them is being abandoned.

| | Losing ground | More load-bearing than ever |
|---|---|---|
| **Name** | Design speculation | Engineering rigor |
| **What it is** | Architecture documents, requirements specifications, multi-week design debates held *before* anyone has touched the problem | Small batches, continuous integration, tests, code review, verified claims, fast revert, recorded decisions |
| **What it does** | Predicts the shape of a system nobody has built | Makes being wrong cheap |

Conflating these produces both common errors. Read "stop planning" as
abandoning the right-hand column and you get an unreviewable mess. Read
"be rigorous" as reinstating the left-hand column and you get a forty-page
design document for a system nobody understands yet.

**The second column is the reason the first can be dropped.** A team that
can revert in minutes does not need to predict; it can find out. A team on
three-month integration branches genuinely does need the design document,
because for them being wrong is expensive.

Adam Wolff, on the Claude Code engineering team, describing how his team
changed:

> We used to spend a lot of time debating, design docs, design
> discussions, extensive requirements, POCs… Now we can throw this away
> and we can find out. You do not plan this kind of design, you discover
> it through experimentation.

Note what makes that true for his team and possibly false for yours:
throwing a change away costs them an afternoon. That condition is doing
all the work in the sentence.

---

## 03 · Sort every open question by the cost of being wrong

This is the whole decision procedure, and it replaces "how much should we
plan" with something answerable. For each open question, ask what it costs
to discover you chose badly.

| Question in the PyMOL Copilot | Cost of being wrong | Method |
|---|---|---|
| Does the agent call PyMOL directly or through a command queue? | An afternoon; delete the branch | Build one, keep it if it works |
| Does this system prompt make selections more reliable? | Minutes; re-run the corpus | Measure it |
| Should the agent render images itself or hand back a script? | A day of rework | Try the simpler one first |
| Which requests belong in the evaluation corpus? | Everything downstream is graded against the wrong target | Interview real users; think hard |
| What does the plugin's public API look like? | Other people's scripts break on every change | Design it; record the decision |
| Do we fine-tune, and on what data? | Months of collection, possibly wasted | Defer until the failures say |

The failure mode is applying one method to the whole table. A design
document for row one is waste. Improvising row four is worse than waste —
it produces a project that cannot tell whether it is succeeding.

This is the same axis as `docs/plan.md`'s "risk overrides size": the
question is never how big the change is, it is how hard it is to take
back.

---

## 04 · Stating intent, when the outcome isn't readable

Here is the part that is genuinely different about a model-backed product,
and it is a change of *instrument*, not of method.

For ordinary software, you state intent in prose and verify by reading the
diff. "Duplicate slugs should raise, with a regression test" — you can
read the change and know whether it does. That is Canon's normal loop:
a plan states intent, a diff is produced, a reviewer reads both. No
special machinery.

For a model-backed product, reading the diff tells you nothing. "The agent
should colour the binding pocket correctly" cannot be verified by
inspecting source, because the behaviour lives in a probability
distribution rather than in the code. Prose intent becomes unfalsifiable
exactly when you need it most.

So intent has to be stated in a form that can be checked. For PyMOL
Copilot, the first artifact in the repository — before any code — is
roughly thirty real requests with what a correct outcome looks like:

```
- request:  "Color the binding pocket of 1ABC by hydrophobicity"
  expects:  selection within 5 Å of the ligand; a hydrophobicity colour
            scheme applied; the rest of the structure untouched

- request:  "Align these two structures and tell me the RMSD"
  expects:  cmd.align run; RMSD reported with the atom count it was
            computed over; chain mismatch surfaced, not silently accepted

- request:  "Why does this helix look broken?"
  expects:  identifies the missing residues in the density;
            does not invent a fix or model in coordinates

- request:  "Make a figure for a paper"
  expects:  asks what to emphasize and at what size before rendering
```

**This is not a rival artifact to the plan. It is the plan's `## Success`
section, written in the only form that can be verified.** It states intent
by example, states non-goals by omission, is falsifiable, and — unlike an
architecture document — does not go stale, because it describes what users
want rather than how the system is built.

Look at the second halves of those entries: *surfaced, not silently
accepted*; *does not invent a fix*; *asks before rendering*. Each encodes
**judgement rather than capability**. That is where most of the product's
value sits, and it is exactly the material that never survives the trip
into a requirements document.

### This is test-first, not waterfall

Writing the corpus before the code is test-driven development applied to a
system whose output is non-deterministic. Grading is probabilistic instead
of binary; that is the only difference. Anthropic's own security
engineering team describes moving *toward* this, not away — from "design
doc → janky code → refactor → give up on tests" to "guide it through
test-driven development, and check in periodically."

And Canon already does this to itself. Its Phase 3 rule — "no instruction
line ships without an eval that fails when you remove it" — is the same
move: intent stated as graded cases, because prose about what an
instruction achieves is not checkable.

---

## 05 · The loop, worked through PyMOL Copilot

Each stage depends on the one before it. The order is the point: nothing
after stage three is decidable before stage three has run.

**1 · Write the corpus. No code yet.**
Twenty to fifty cases, collected by talking to two or three people who use
PyMOL daily. This is a real week of work and it is the week that matters
most. You are not designing anything — you are recording what "good" means
while you still have access to people who know.

**2 · Build the dumbest thing that could pass it.**
An off-the-shelf model, PyMOL's Python API exposed as tools, nothing else.
No fine-tuning, no retrieval, no orchestration, no routing. Likely a few
hundred lines. The goal is not quality; the goal is a number.

**3 · Run the corpus. Write down the score.**
This number is the first real thing the project owns. Every later decision
is judged as a movement in it. Before it exists, every architectural
opinion in the project — including yours — is a guess with a confident
tone.

**4 · Read the failures, not the successes. Cluster them.**
This is where design gets *discovered*. You might find that 60% of
failures are the model misunderstanding PyMOL's selection algebra, 25% are
it not knowing the current session state, and 15% are confident
crystallographic errors. Three clusters, three unrelated fixes. You could
not have guessed that ratio, and the ratio is what determines the
architecture.

**5 · Fix the largest cluster with the cheapest adequate instrument.**
Selection-algebra confusion wants a skill with worked examples. Missing
session state wants a tool that returns the loaded objects. Only a genuine
domain-knowledge gap wants training data. Then re-run. **If the number did
not move, you were wrong about the cause** — and you lost a day rather
than a quarter.

### On committing to a fine-tuned model up front

"With a custom fine-tuned model" is an answer chosen before the question
was measured. Fine-tuning costs a data pipeline, a training loop, an eval
harness you need anyway, a serving story, and a repeat every time the base
model improves.

The realistic outcome of stage four is that most failures are *context*
problems — the model does not know what is loaded, or what the user means
by "pocket" — and context problems are fixed with a tool in an afternoon.
If a stubborn knowledge gap survives stage five, fine-tune then: you will
have two hundred logged failures telling you exactly what to train on,
which is a far better position than guessing at a dataset in month one.

This is the general rule stated in Anthropic's *Building Effective
Agents*: start with the simplest solution, and add complexity only when it
demonstrably improves outcomes.

---

## 06 · What you still write down

Dropping speculative design is not dropping documentation. Three artifacts
survive, each earning its place by the rule `docs/plan.md` §06 already
states: **a section is required only if something actually reads it.**

### The feature plan — intent, at the altitude of the whole project

Why this exists, who it is for, what success looks like, what is
explicitly out of scope, and an ordered list of branch-sized pieces. What
it does *not* contain is an architecture section pretending to know the
shape of something nobody has built.

```markdown
## Why
Structural biologists spend more time fighting PyMOL's selection
syntax than looking at structures.

## Success
Graded against `evals/corpus.yaml`: a working biologist completes a
real figure-making task by asking, without consulting the
selection-algebra documentation.

## Non-goals
- Not a replacement for the PyMOL GUI.
- Not structure prediction. We show what is there.
- No fine-tuning until the baseline says where it would help.

## Steps
- eval-corpus:  30 graded requests with expected outcomes
- pymol-tools:  expose cmd.* to an agent, no intelligence yet
- baseline:     run the corpus against a stock model, record it
- ...remaining steps derived from the failure clusters
```

That last line is not laziness. It is the plan honestly reporting that the
next decisions are not yet knowable, which is more useful than four
invented steps that will be deleted.

### The branch plan — scope, done, and proof, for one pull request

One branch, one pull request, one plan. It names the paths it may touch,
the one-line definition of done, the non-goals a competent agent would
otherwise plausibly violate, and the command that must pass. Canon's
`plan` skill already asks for exactly these, and its `PostToolUse` hook
saves them.

Two pieces of craft worth restating:

- **A non-goal is only useful if it was tempting.** "Don't rewrite the
  module" earns its line; "don't break anything" is noise.
- **If you could describe the diff in one sentence, skip the plan.**
  Planning is overhead and should be spent where uncertainty is.

### The decision record — why, written when it lands

Code cannot say why an alternative was rejected. Write the record when the
change merges, not when it is proposed: a decision reversed during
implementation was a draft opinion, and drafts do not need archiving. The
test is two-part — an alternative was seriously considered, *and* the
consequence outlives this branch.

For PyMOL Copilot, "we call `cmd.align` rather than `cmd.super` by
default, because our corpus is dominated by close homologs" is a record.
"We named the module `tools.py`" is not.

---

## 07 · Trunk-based development is the prerequisite, not the casualty

Everything above depends on one assumption: that being wrong is cheap.
Trunk-based development is the machinery that makes that assumption true.
Small batches, integrate daily, keep trunk green, ship behind a toggle,
revert in minutes — every one of those practices exists to lower the cost
of a bad decision.

This is also not new. "The advantage is the speed at which you learn, not
the speed at which you ship" restates the continuous-delivery thesis,
which has argued against big design up front since well before language
models. What changed is not the argument but the break-even point:
implementation got cheap, so the range of questions worth settling by
experiment got much wider.

The loop in §05 runs on trunk without modification. `eval-corpus` is a
pull request. `pymol-tools` is a pull request. `baseline` is a pull
request. What you skip is the architecture document — not the branch
discipline.

**Where the friction is real.** Two places, both worth naming rather than
papering over:

- **Review capacity becomes the constraint.** Agents produce changes
  faster than humans review them, and trunk-based development assumes
  prompt review. An automated verdict can be evidence; it can never be
  approval.
- **"Discovery" quietly becomes a long-lived branch.** If experimentation
  turns into one exploratory branch running three weeks, you have
  abandoned trunk-based development while believing you are being modern.
  Each probe gets its own branch and its own day.

---

## 08 · What "revert" actually means

In trunk-based development, undo is usually not a git operation at all.
There is a ladder, climbed from the top; git appears near the bottom.

| | Mechanism | Cost | Notes |
|---|---|---|---|
| 1 | **Turn the flag off** | Seconds | No build, no deploy, no git. This is why feature flags and trunk-based development are taught together — the toggle is what lets unfinished work sit safely on trunk. |
| 2 | **Roll forward with a small fix** | Minutes | The default for an ordinary defect. Trunk has moved since your change; a two-line fix is usually safer than untangling a revert. |
| 3 | **Redeploy the last good artifact** | Minutes | The running system goes back; the repository is untouched. Buys time to fix properly. |
| 4 | **`git revert <sha>`** | An hour | A new commit applying the inverse, so trunk history stays append-only. For a merge commit you need the mainline parent: `git revert -m 1 <sha>`. |
| — | **`reset --hard`, force-push** | Never | Rewriting shared history corrupts every other clone. This rung is not on the ladder. |

Canon encodes that last row directly: its git guard blocks force pushes
and hard resets while leaving `git revert` untouched.

**The trap everyone hits once.** After you revert a merge, *re-merging
that branch later does nothing* — git's merge base still considers those
commits present, so it has nothing to bring. The fix is to revert the
revert, or rebuild the work on a fresh branch. Knowing this in advance
saves an afternoon of genuine confusion.

### Revertability is designed in, not commanded

`git revert` only works if the commit was small and self-contained. A pull
request that combined a bug fix, a refactor and a dependency bump cannot
be reverted, because reverting it removes two things people now depend on.
Instead you hand-patch under pressure at the worst possible moment.

In a large study of agent-authored pull requests, roughly **40% combined
multiple unrelated tasks**, and "too large" ranked among the top three
reasons such changes were rejected outright. Read that as a revertability
statistic: those are changes nobody can cleanly take back out. "One
branch, one pull request" and an explicit `## Non-goals` section are not
tidiness — they are what keeps the undo button connected to anything.

---

## 09 · One-way doors

The ladder stops at changes already consumed by something outside your
repository. For these, the classical answer and the modern answer agree
completely: think hard, write it down, get a second reader.

- **Destroyed data.** Reverting a migration restores the script, not the
  dropped column's contents.
- **Published interfaces.** A released package version, or a PyMOL Copilot
  plugin API that other people's scripts now call.
- **External side effects.** Emails sent, webhooks fired, payments taken,
  resources provisioned.

The standard technique for turning a one-way door into a sequence of
reversible ones is **expand and contract**: add the new column, write to
both, backfill, read from the new one, and only then — in a later release
— drop the old. Each step reverts cleanly; the combined change never would
have.

**Small does not mean safe.** A three-line change that drops a column,
widens a permission or alters a public signature deserves more scrutiny
than a three-hundred-line change that adds tests. Size heuristics are
about review capacity; risk heuristics are about reversibility. They are
not the same axis, which is why Canon dispatches a `risk-reviewer` on
auth, data and migration surfaces regardless of diff size.

---

## 10 · Probes are deleted, not merged

The classical discipline is that a spike is time-boxed and thrown away,
with the real implementation written afresh using what it taught you.
Agents make spikes so cheap that the temptation to merge one is enormous —
the code exists, it works, deleting it feels wasteful.

Merging it trades design debt for code debt at a poor exchange rate. You
now maintain exploratory code that was never meant to survive, written to
answer a question rather than to serve users, and you have given up the
clean-room implementation the spike was supposed to buy.

There is also a purely practical argument: **if the probe never lands on
trunk, undo is `git branch -D`** — instant, free, no history, no
merge-base trap. The undo cost of an experiment should be zero, and it
stays zero exactly as long as you do not merge it.

For PyMOL Copilot: the five throwaway attempts at getting the model to
reason about selection algebra get deleted. What survives is a line in the
corpus recording what you learned, and possibly one skill file containing
the approach that worked.

### "But what if my probe is big?"

This is the question everyone arrives at, and it usually sounds like
this: *I am building a probe. It takes four slices, so four pull
requests, all merged to main. Now I want to throw it away — isn't that
a problem?*

Yes, that would be a problem. But the problem is not in the throwing
away, it is one step earlier: **a probe that needs four pull requests is
not a probe.**

If you are slicing exploratory work into four merged pull requests, one
of two things has happened. Either you stopped probing and started
building — you are committed, so stop calling it a probe and plan it
properly. Or you are trying to answer four questions at once, in which
case it is four probes, done one after another, each of which you delete
before starting the next.

Neither of those is fixed by better revert technique. They are fixed by
noticing which situation you are in before you open the first pull
request.

### The test to apply before merging anything exploratory

Ask one question about each piece of work in front of you:

> **If the answer to my question turns out to be no, would I still want
> this?**

- **Yes** — merge it. It is not probe. It is infrastructure that the
  probe happens to need, and you would have built it anyway.
- **No** — do not merge it. That is the probe, and it lives on a single
  branch that gets deleted.

The reason this test works is that it separates two things that feel
identical while you are writing them and are completely different a
month later. Code you would want regardless is an asset the moment it
lands. Code that only exists to answer a question is a liability the
moment the question is answered.

Nearly every "my probe needs four pull requests" turns out to be three
of the first kind and one of the second.

### Worked example: "does fine-tuning help PyMOL Copilot?"

That question genuinely looks like four slices of work. Apply the test
to each one:

| Slice | Would I still want this if the answer is no? | So it is |
|---|---|---|
| A data pipeline that produces training examples | No | Probe |
| The fine-tuning / training loop | No | Probe |
| An eval harness that scores the result | **Yes** — every other decision needs it too | Infrastructure |
| Serving the custom model in production | No | Probe |

Three of those four should never have been pull requests. And once you
see that, the probe collapses to something much smaller:

- **Eval harness** — merge it. You wanted it regardless; it is stage 3
  of the loop in §05 and every later decision is measured with it.
- **Data pipeline** — do not build one. Hand-label two hundred rows in a
  spreadsheet. A probe answers its question at the lowest fidelity that
  is *decisive*, not at production quality.
- **Training loop** — one script, one branch, never merged.
- **Serving** — do not. Evaluate offline. Serving only matters if the
  answer turns out to be yes, and you do not know that yet.

What you end up with is **one merged change you wanted anyway, and one
branch you delete.** Throwing the probe away costs a single command.

### The skill this is really teaching

Designing the cheapest experiment that still settles the question.

A junior engineer's instinct, and it is an understandable one, is to
build the probe properly — real pipeline, real tests, real deployment —
because building things badly feels unprofessional. But a probe is not a
product, and the professionalism is in the *experiment design*, not in
the finish of the code. A hand-labelled spreadsheet that answers the
question in two days is better engineering than a polished pipeline that
answers the same question in three weeks.

So when a probe looks like it needs four pull requests, the correct
response is not to slice it more carefully. It is to ask what the
cheapest thing is that would still change your mind, and build only
that.

### Three shapes, and knowing which one you are in

Most of the confusion comes from calling all exploratory work "a probe".
There are three distinct shapes, and they get different treatment:

1. **A probe.** One question, one branch, hours to a day or two. Never
   merged. Deleted when the question is answered. What survives is a
   line in the corpus and what you now know.
2. **A bet.** Genuinely large, and genuinely cannot be shrunk into a
   probe. This is not exploration any more — you have decided to build
   something. Give it a feature plan with `## Why`, `## Success` and
   `## Non-goals`, merge it in small slices, and accept that removing it
   later means a deletion pull request. That cost is real, but it is
   bounded precisely *because* the slices were small and cohesive.
3. **A spike.** Multi-week exploration on a branch that is never merged.
   Legitimate, as long as it is time-boxed and you accepted on day one
   that it gets deleted.

The failure mode is a fourth shape that pretends to be the third: **a
long-lived branch you intend to merge.** That is how you end up merging
a probe you should have thrown away, and it is the thing to watch for in
yourself. The tell is that you have stopped asking a question and
started polishing.

### When several probes are needed, run them in sequence

If four questions genuinely need answering, do not build four things in
parallel and merge them. Run probe one, delete it, and build probe two
fresh using what you learned. You are not accumulating code, you are
accumulating knowledge — and the knowledge lives in the corpus and in
the decisions you record, not in the branch.

This feels wasteful the first time. It is not: the second probe is
faster than the first *because* it was written knowing the answer to the
first question, and it carries none of the scaffolding the first one
needed.

### Nothing enforces any of this

Worth stating plainly: Canon has no concept of a probe. It will happily
save a plan for one, gate its verification and dispatch a reviewer. It
cannot tell exploratory work from committed work, because the difference
is intent that only you hold, and storing it would break Invariant II.

So this is a judgement you make, not a rule a tool applies. What the rest
of the method gives you is the thing that makes the judgement
recoverable when you get it wrong: every merged slice has a stated scope
and a stated set of non-goals, so when you do have to delete one, you can
see exactly what crossed its boundary.

---

## 11 · What not to adopt, and the evidence for refusing

A family of specification frameworks has grown up around coding agents.
They generate a constitution document, a requirements document, a research
document, a data-model document, an interface-contracts directory and a
task list, each behind an approval gate. The published experience is
consistent enough to act on.

| Finding | Source |
|---|---|
| A first feature produced **2,577 lines of specification markdown for 689 lines of code**; 33.5 minutes of agent time against 8 minutes for plain iterative prompting, at comparable quality — and a trivial bug still slipped through. | Scott Logic, spec-kit retrospective, 2025 |
| Heavy generated specifications cause models to lose focus and ignore details that were stated — the context is diluted by its own paperwork. | spec-kit issue tracker, "creates the illusion of work" |
| Four named failure modes: maintenance burden, **missing "why" context**, false completeness, and specifying at the wrong abstraction level. | Practitioner analysis, isoform.ai |
| "Frameworks often create extra layers of abstraction that can obscure the underlying prompts and responses… making it tempting to add complexity when a simpler setup would suffice." | Anthropic, *Building Effective Agents* |

Worth dwelling on the third row. Heavy specifications capture *what* in
exhaustive detail and lose *why* entirely — which inverts the priority,
because *why* is the part that stays true after the design changes. That
is the same conclusion `docs/plan.md` reaches about decision records:
"they document *why*, which is the one thing the code cannot say."

The name is not the problem. "Intent-driven development" as a movement
traces to Sean Grove's *The New Code* (mid-2025) — the specification as
the durable artifact, code as its compiled output — and spec-kit and Kiro
are both downstream of it. The idea is right. The execution has mostly
been an attempt to state intent by volume, which is the one way to
guarantee it will not be read.

---

## 12 · The short version

- **Sort by the cost of being wrong.** Cheap to reverse: build it and find
  out. Expensive to reverse: think, write it down, get a second reader.
- **State intent in the form that can be checked.** Prose where a diff
  answers the question; graded examples where it cannot. For a
  model-backed product the corpus *is* the intent statement, not a rival
  to it.
- **Build the dumbest thing that could pass it, then read the failures.**
  The failure clusters, not your architectural intuition, tell you what to
  build next.
- **Write down why, scope, non-goals and proof. Not speculative
  architecture.** Skip the plan entirely when the diff fits in one
  sentence.
- **Keep every change revertable.** One branch, one pull request. Flags
  before reverts, reverts before rewrites, never a forced push on shared
  history.
- **Treat one-way doors differently.** Data loss, published interfaces and
  external side effects get the full classical treatment regardless of
  diff size.
- **Delete your probes.** Before merging anything exploratory, ask: *if
  the answer turns out to be no, would I still want this?* Yes means it
  is infrastructure — merge it. No means it is probe — keep it off
  trunk. A probe that needs four pull requests is not a probe.
