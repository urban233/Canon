# Canon

*Successor to CoDev — plan v1*

A Claude Code plugin that holds the thread, so the agent doesn't drift and
the work still ships clean.

> This is a markdown rendering of the canonical plan artifact:
> https://claude.ai/code/artifact/1453894c-9e0b-40fe-b661-d5f0e53eca5f
>
> **The artifact is the source of truth if the two ever diverge.** Per §14,
> Canon is built to this document and to CoDev's recorded experience — it is
> not discovered by using the tool.

CoDev's instincts were right and its mechanism was wrong. It tried to make a
workflow reliable by *recording* where the work stood, and the record
became the thing that broke. Canon keeps the instincts, throws away the
record, and rebuilds the whole thing on four Claude Code primitives: skills,
subagents, hooks, and one small MCP server.

It builds on plan mode rather than around it. Claude Code already writes and
reviews plans well; what it doesn't do is *keep* them. That, and five other
specific places a long session loses the thread, is Canon's whole surface
area.

*13 Sep 2026 · Grounded in CoDev @ f5701c7 · 45 ADRs read · No code changed
at time of writing*

---

## 01 · Evidence — The state machine spent most of its rounds fighting itself

This isn't a taste judgement. CoDev keeps a receipt of its own operation in
`.codev/task/`, and the receipt is damning. Across twelve tasks, here is
what the lifecycle actually recorded:

| | |
|---|---|
| **47 / 73** | rounds that had to be *reopened* by hand rather than advancing on their own (`round-state.json`) |
| **37 / 50** | escalations logged as `critical_interrupt` — a human overriding the machine (`escalations.jsonl`) |
| **29** | rounds on a single slice, 21 of them reopens, before it reached review (`claude-code-adapter…`) |
| **59** | coverage waivers written to say a review dimension didn't apply (`coverage_waivers`) |

The interesting part is *why* the interrupts happened. They are not
disagreements about the code. Four consecutive entries from the escalation
log:

> **round 24** — "…detected for a plan-writing step, not new content drift.
> Re-baselining onto the accepted plan's own head before builder dispatch."
>
> **round 25** — "Previous resume passed a short-form SHA (1aca1b9) as
> `--head`, which `reopen()` stores verbatim rather than canonicalizing…
> so it never matched HEAD and the drift check re-tripped."
>
> **round 26** — "`codev task record --role reviewer`'s own auto-commit
> lands one commit past the `--head` value passed to it… tripping
> `stop_drift` the same way `reopen()`'s own commits have each time in this
> session."
>
> **round 27** — "`codev task style --set delegate` landed a legitimate but
> untracked commit on top of round 27's `base_snapshot`. Re-baselining onto
> the actual current head."

Every one of those is CoDev's own bookkeeping commit invalidating CoDev's
own stored snapshot. The workflow tool had become the largest source of the
drift its drift detector was built to catch. That is not a bug to fix; it
is what happens when you store a fact that git already knows.

## 02 · Diagnosis — Three failure modes, one root cause

**Stored position instead of derived position.** `round-state.json` holds
`base_snapshot`, `current_round`, `current_slice`, `reopens`,
`coverage_waivers`, a schema version (now 4, with v2 files hard-rejected).
Every one of those is either already in git and GitHub, or is an opinion
that could be recomputed. Because it is stored, it can disagree with
reality — and it does, constantly, because the act of writing it changes
reality. Thirteen `check` outcomes fan out into a routing table in
`navigator.py`; when the input state is wrong, all thirteen are wrong.

**Ceremony priced as if it were free.** Eight mandatory coverage
dimensions, five outer-loop specialists, a waiver per dimension per round
with prose justification. One slice filed eighteen waivers. A one-line
bookkeeping flag stranded off `main` became an explicit chat exchange. The
gates themselves are the right gates — the cost is that each one plays out
narrated, in the foreground, as a step the developer has to watch.

**Instruction bloat, measured and still growing.** CoDev's own budget test
records **34,389 bytes** of instruction loaded before any work begins:
15.5 KB of agent guidelines, 7 KB of `AGENTS.md`, 3.5 KB of `CLAUDE.md`,
6.9 KB of skill descriptions. Meanwhile the Claude Code team deleted more
than 80% of their system prompt for the Opus 5 generation and measured no
quality loss. A prompt is mostly scar tissue from a previous model's
mistakes.

> **The root cause under all three:** CoDev models the *process*. Canon
> should model only the *evidence*. Process state has to be maintained,
> migrated, repaired and reconciled; evidence is just facts that already
> exist somewhere — a diff, a green test run, a reviewer's verdict, a PR
> approval. Facts don't drift.

## 03 · The ledger — What crosses over, and what stays behind

CoDev is 14,008 lines of Python across 17 modules, 23,630 lines of tests, 68
CLI subcommands, four platform adapters and 45 ADRs, built in about five
weeks. Most of that is machinery for problems a Claude Code plugin simply
doesn't have. A little of it is genuine, hard-won judgement.

### Keep — and why

- **The focus card's six questions.** Change, success, non-goals, allowed
  scope, validation, stop-if. The questions are the best anti-drift device
  CoDev has — but not as a separate document. In Canon they become front
  matter on the plan Claude Code already writes.
- **Review as an isolated subagent.** Right for the right reason: a
  reviewer needs the diff and the criteria, nothing else. Isolating review
  is cheap; isolating implementation costs context at every handoff. CoDev
  already concluded this — keep the conclusion.
- **"You may self-check, you may never self-approve."** One sentence that
  does more work than the entire eight-dimension coverage matrix.
- **Gates ask, never refuse; gates fail open.** A guardrail that errors
  must never block work. This is what makes hooks tolerable rather than
  infuriating.
- **Risk overrides size.** Permissions, data, public APIs and destructive
  operations get full scrutiny at any diff size. Canon derives this from
  the diff instead of asking a human to assert it.
- **One step, one branch, one PR.** Small, self-contained changes are the
  highest-leverage property of an agentic PR, and the research backs it.
  Canon keeps the shape and drops the `slice`/`task` object model that
  carried it — see §06 on terminology.
- **Stop after two attempts at the same root cause.** Free to implement,
  prevents the most expensive failure mode there is.
- **The ADR practice — written by the agent.** Decision records were one of
  CoDev's genuinely good ideas: they document *why*, which is the thing
  code cannot say and the thing a developer returning after months needs
  most. Canon ships the practice to every project that installs it, and the
  agent authors the records. §06 has the mechanism.
- **The planning skills' questions.** Not their documents. CoDev's five
  planning skills collapse into one conversational `frame` skill that
  writes into the feature plan; the reference skills — testing craft,
  technical writing — port verbatim, since they carry knowledge with no
  lifecycle attached. See §06.

### Drop — and why

- **The round-state machine.** The evidence above. No `round-state.json`,
  no `base_snapshot`, no schema version, no reopen path, no
  thirteen-outcome routing table. Position is computed on demand or it
  doesn't exist.
- **Eight coverage dimensions and per-dimension waivers.** 59 waivers
  written to say "not applicable". The diff already knows whether it
  touched auth, concurrency or a migration. Ask the diff.
- **The installer, adapters and bundle machinery.** 1,896 lines of
  installer, a conflict wizard, `diff`/`update`/`remove`, four platform
  adapters. `/plugin install canon` replaces all of it with zero lines of
  Canon code.
- **68 CLI subcommands.** A CLI needs a shell and an installed Python
  package in the target repo. That is exactly the surface that doesn't
  exist identically in Slack, on the web, or in a cloud sandbox.
- **The five-specialist outer loop with dispatch authorization.** Five
  parallel reviewers plus a human gate on *selecting* them. Canon dispatches
  reviewers the diff calls for, and one by default.
- **The task/slice/work-style/entry-mode object model.** Four concepts and
  four ADRs to express "this branch, this change". Git expresses it
  already.
- **ADRs about the workflow's own process.** Not ADRs — those stay, see
  §06. But of CoDev's 45, a large share decide how CoDev itself should
  behave, which is why 0024→0040→0044 and 0034→0039 superseded each other
  within weeks. Records about the product outlive it; records about the
  process churn.
- **34 KB of loaded instruction.** Canon starts near zero and earns each
  line back through `claude plugin eval`. See §13.

## 04 · The whole idea — Three invariants a developer can hold in their head

If Canon is understandable, it's because there are only three rules and
everything else is a consequence of them. A developer should be able to
explain Canon to a colleague in thirty seconds.

**I. The plan is in the repo before the first edit.** Not a Canon document —
*the* plan, the one Claude Code's plan mode already produces, saved into the
repository at a standard path with a small machine-readable header. Because
it's git-tracked, revising it is a visible diff rather than a silent
reinterpretation, and because it's the same plan the developer approved on
screen, there is no second artifact to learn or keep in sync.

**II. Position is derived, never stored.** "Where does this work stand?" is
a pure function of the branch, the `base..HEAD` diff, the plan's status
line, the PR, its checks and its reviews. Canon caches nothing that git or
GitHub already knows. There is no state file to drift, repair, migrate or
reopen — and no bookkeeping commit that can invalidate it.

**III. Nothing ships on the agent's own word.** Every claim that gates
progress must be reproducible by something that isn't the agent that made
it: the test command actually run by a hook, the reviewer subagent that
never held the writer's context, the human approval on the PR. "I ran the
tests and they pass" is not evidence; an exit code captured by a `Stop` hook
is.

This one is load-bearing enough to be a **precondition**: Canon does not
operate in a repository where it has no way to check the agent's word. See
§07.

And evidence is *re-established*, never filed. Canon may cache only a pure
function of an immutable input — and in practice it caches nothing at all,
because everything worth knowing is one command away. **"Did this turn end
green?" lives inside the hook that asked. "Is this branch green?" is CI's
answer, keyed by the same SHA, already in GitHub.** A record Canon keeps is
a record Canon has to keep right.

## 05 · Architecture — Four primitives, each doing the one job it's good at

Claude Code gives a plugin four extension points, and they are not
interchangeable. Canon's structure is just an honest mapping of jobs onto
them: **hooks are the things the agent cannot talk itself out of**,
**skills are procedures the agent reads when relevant**, **subagents are
fresh context**, and **the MCP server is the one place that answers
questions about state**.

```
canon/
├── .claude-plugin/plugin.json      name, version, description
├── hooks/hooks.json                the spine — §07
│   └── hooks/*.py                  small, fail-open, no deps beyond stdlib
├── skills/
│   ├── frame/SKILL.md              feature altitude: the questions, not a form
│   ├── plan/SKILL.md               shape what plan mode drafts
│   ├── build/SKILL.md              implement against the saved plan
│   ├── review/SKILL.md             dispatch + read back review
│   ├── decide/SKILL.md             write the decision record, at merge
│   ├── ship/SKILL.md               PR, checks, hand to a human
│   └── + ported reference skills: testing-craft, technical-writing-style, …
├── agents/
│   ├── reviewer.md                 read-only. the default, always.
│   ├── risk-reviewer.md            auth / data / migration surfaces
│   └── scout.md                    read-only repo grounding, keeps main context clean
├── .mcp.json → canon-server        position, plan, evidence — §08
└── settings.json                   defaults only; never force-enables an agent
```

### Why an MCP server and not a CLI

This is the decision that makes Slack, the IDE and the terminal behave
identically. A CLI requires a shell, a PATH, and a package installed into
the target repository — three things Canon cannot assume in a cloud sandbox
or a Slack-initiated session, and three things that were a large fraction of
CoDev's code. An MCP server ships *with the plugin*, is available the
moment the plugin is enabled, returns structured data rather than text the
agent has to parse, and works the same in every surface Claude Code runs
in.

The server stays small on purpose — five tools, no more. Everything it
returns is computed at call time from git, GitHub and the working tree. It
owns no database.

### Stack and delivery

A new repository under **BSD-3-Clause**, matching CoDev so the ported
skills stay licence-compatible, built with **Bazel**. Python throughout, but
split deliberately in two.

| Component | Built how | Delivered how |
|---|---|---|
| Hooks | Plain Python, **standard library only**, not Bazel-built artifacts | Run in place from the plugin directory. They fire on every tool call, so there is no room for dependency resolution in that path — and a guardrail that can fail to start is worse than no guardrail. |
| MCP server | Bazel-built wheel, on the **official MCP Python SDK** | `uvx` from `.mcp.json` — zero install, resolved on first run. |
| Skills, agents | Markdown | Shipped in the plugin. Nothing to build. |

The one consequence worth stating: because the server uses the official SDK
it has a dependency, so `.mcp.json` cannot simply call `python3 -m canon`
and hope the package is present. `uvx` resolves it on first run and needs
nothing installed ahead of time, which is what keeps a plugin install a
single step.

```jsonc
// .mcp.json at the plugin root
{
  "mcpServers": {
    "canon": {
      "command": "uvx",
      "args": ["canon-mcp@<pinned version>"]
    }
  }
}
```

Bazel builds and publishes that wheel; `uvx` fetches it. The version is
pinned rather than floating, so a plugin update and a server update are one
decision instead of two — the same reason the plugin manifest carries an
explicit `version`.

### Why the reviewer is a subagent and the builder is not

CoDev arrived at this and it's worth restating because it's
counter-intuitive: delegating *implementation* is usually a loss. Every
handoff costs the context the main session already has — the conversation,
the repository facts, the developer. Delegating *review* is a pure win,
because a reviewer's value comes precisely from *not* having seen the
writer's reasoning. Canon therefore implements in the developer's own
session by default, and isolates only the checks.

## 06 · Planning — Claude Code already writes the plan. Canon keeps it.

Plan mode is the best planning surface either of us is going to build, and
it already exists: `Shift+Tab` to enter, Claude reads the codebase before
touching anything, `Ctrl+G` opens the draft in your own editor, and with
cloud drafting you review it in a browser and **leave inline comments on
individual sections** rather than replying to the whole thing. Canon must
not compete with any of that.

It has one gap, and only one: approved plans land in `~/.claude/plans`,
outside the repository, swept after thirty days. They aren't reviewable in
a PR, aren't visible to a colleague, don't travel between the terminal and
Slack, and can't be read by a hook. **That gap is the entire job.**

### The mechanism: one hook, at save time

Approving a plan is a tool call — `ExitPlanMode` — so a `PostToolUse` hook
matched to it fires the moment the developer says yes. That hook writes the
approved plan, verbatim, to `.canon/plans/<branch>.md` and prepends a
header it derives itself.

The header is where the focus card's six questions go. The developer types
none of it — the hook fills in what it can read (branch, base SHA,
changed-paths intent, the repo's verify command) and leaves a field blank
rather than inventing it. Blank fields are the only thing the `plan` skill
asks about, and it asks once.

```
# .canon/plans/fix-slug-collision.md  — written by the hook, not by hand
---
status:   approved          # draft | approved | superseded
base:     a41f0c9           # where this branch left main
scope:    [src/slugs/**, tests/slugs/**]
done:     "duplicate slugs raise, with a regression test"
verify:   just test
parent:   features/public-permalinks.md
---

↓ everything below is the plan mode output, unaltered ↓

## Approach            conventional — plan mode writes this anyway
## Non-goals           REQUIRED — read by the scope check and the reviewer
## Verification        REQUIRED — read by the Stop hook
## Risks / Stop if     conventional
## Open questions      conventional
```

Two properties make this cheap. The body is **never rewritten** — whatever
plan mode produced is what's on disk, so no format is imposed on the
developer and inline comments they made upstream are reflected in the text
they approved. And the header is **derived, not demanded**, which keeps
Invariant II intact: if the header disagrees with git, git wins and the
hook says so.

### On the name

"Charter" fails. The better answer isn't a better coinage — it's **no new
noun at all**. This is the plan. A developer opening `.canon/plans/` needs
no glossary, and Canon loses a concept instead of renaming one. If the
header ever needs a name of its own in conversation, it's the plan's
*header*.

### How far the standard goes

An earlier answer here was that the plan body should be entirely
unconstrained. That's an overcorrection, and **Non-goals is the proof**: it
is the single most valuable section in an implementation plan and the one
most reliably skipped, precisely because writing it feels like stating the
obvious right up until the agent does the obvious thing.

So the standard needs a rule that admits required sections without sliding
back into ceremony: **a section is required only if something actually
reads it.**

| Section | Status | What reads it |
|---|---|---|
| `## Non-goals` | **required** | The `PostToolUse` scope check, and the reviewer's brief — so a deliberate omission is never written up as a gap. |
| `## Verification` | **required** | The `Stop` hook: which command runs, and what counts as done. |
| `## Approach` | conventional | Humans. Plan mode writes it unprompted; Canon never asks for it. |
| `## Risks / Stop if` | conventional | Humans, and the agent's own escalation judgement. |
| `## Open questions` | conventional | Humans, and the next session after a compaction. |

Two sections earn their place by doing work; the rest are habits worth
having and nothing more. The mechanism keeps DX intact: the `plan` skill
seeds the headings *while plan mode is drafting*, so they arrive in the
draft you review and comment on inline, rather than as a validator
complaining after the fact. At save time the hook checks only that the two
required ones are present and non-empty. Missing → it asks, once. It never
rejects a plan.

One piece of craft that belongs in the skill rather than the hook: **a
Non-goal is only useful if it was tempting.** "Don't rewrite the module"
earns its line; "don't break anything" is noise. The test is whether a
competent agent, given this plan and no Non-goals section, would plausibly
have done it.

### Planning a feature, not just a branch

Same file format, one altitude up, and no new machinery. A feature plan is
a plan written in plan mode *before any branch exists*, saved to
`.canon/plans/features/<name>.md`. Its header carries `steps:` instead of
`scope:` — an ordered list, each entry one branch and one pull request.
That's it. There is no brief, no design document, no wave plan, no separate
tracker: CoDev had five planning skills and three artifact types above the
implementation plan, and that stack is a large part of what made it feel
like too much.

When you start a step, the branch plan's `parent:` points at the feature
plan. **Linked, never copied** — the one artifact rule from CoDev genuinely
worth keeping. And "which step am I on?" stays derived: `canon_position`
reads the parent's list, checks which branches exist and which PRs merged,
and computes the answer. Nothing is stored, so nothing can be stale.

### Decision records — the agent writes them, always

Decision records document *why*, which is the one thing the code cannot say
and the exact thing a developer returning to their own repository after a
funding gap needs most. Canon ships the practice to every project that
installs it.

What made CoDev's 45-in-five-weeks feel like overhead was never the
records. It was two other things, and both are fixable.

**Fix one: the agent authors them, not the developer.** An architecture
decision is made in conversation — that's the foreground event, and it
already happened. Writing it down afterwards is bookkeeping, and bookkeeping
belongs in the background. So Canon's `decide` skill drafts the record *in
the same turn the decision is taken*, from material already in context, and
commits it into the branch that contains the decision. The developer meets
it in the PR diff like any other file: they read it, they can comment on it
where they already are, and they are never asked to author one or to
approve it separately. If the agent hasn't written one, that is the agent's
failure, not a prompt for the developer.

**Fix two: record at merge, not at proposal.** This is the direct answer to
the superseding chains. CoDev wrote records when a decision was *proposed*,
which is why statuses sat at `Proposed` and why 0024 was superseded by 0040
and then partly by 0044 inside a month — those decisions hadn't survived
contact with the implementation yet. Canon writes the record when the
change **lands**. A decision that gets reversed during implementation or
review never becomes a record at all; it was a draft opinion, and drafts
don't need archiving.

**The test for whether something earns a record** — both halves required:

| Condition | Excludes |
|---|---|
| An alternative was seriously considered | Everything that was simply the obvious way. If there was no alternative, nothing was decided — it just happened. |
| The consequence outlives this branch | Local implementation choices, and — the big one — decisions about the workflow's own process, which is where most of CoDev's churn came from. |

Records live at `docs/decisions/NNNN-slug.md` in the familiar Nygard shape
— context, decision, consequences — because it's a convention developers
already know rather than something Canon invented. A decision that's still
open at plan time stays a `## Decisions` entry in the feature plan with its
alternatives; it's promoted to a record when the branch merges, or
discarded if it didn't survive.

`canon_ship` includes "this branch made a recordable decision and has no
record" in its readiness answer. It is **not a gate** — it never blocks a
human. It's an instruction to the agent to go and write the thing before
handing over, which is what "imposed" should mean here: imposed on the
agent, invisible to the developer.

### Terminology: what to call the pieces

**"Micro-PR" isn't a real term** — it has no formal definition in the
agentic-coding literature. Adopting it would be exactly the move undone with
"charter": a coined noun a developer has to be taught. **Anthropic's own
vocabulary is an adjective, not an object**: a *bounded task*, a *bounded
changeset*. That's the tell. Anthropic has no task/slice hierarchy because
describing a property of the work is enough; you only need a type system
when something has to store and transition between the types — which is
precisely what Canon no longer does.

So: **drop the task/slice object model, keep the discipline it was
protecting.** Canon has two files at two altitudes and no objects at all.
In the feature plan the entries are `steps:` — plain, needs no glossary, and
each one is described as what it becomes: one branch, one pull request.

The discipline itself is worth keeping on evidence rather than taste. In a
large-scale study of agentic pull requests, roughly **40% combined multiple
unrelated tasks**, and "too large" ranked among the top three reasons
agentic PRs were rejected outright. Small and self-contained is the single
highest-leverage property of an agentic change — which is also why
`## Non-goals` above is required rather than conventional. The two answers
are the same answer.

### Framing: structure without the pipeline

"Canon stops at the feature — product framing is just a conversation" is
wrong for the same reason free-prose plan bodies were wrong. An
unstructured framing conversation drifts too: the agent asks scattered
questions, or skips them and starts planning something nobody agreed to.

What was actually valuable in CoDev's five planning skills was never the
documents. It was the **coverage** — the set of questions a competent
engineer asks before designing anything. That's knowledge, and knowledge is
cheap to keep. The documents, their status lines, their acceptance gates
and their ADR practice were the expensive part, and none of it was the
value.

So Canon takes one skill, `frame`, and it is a conversation with a
checklist held privately rather than a form to fill in. It runs before plan
mode at feature altitude, surfaces only the items genuinely still open, and
writes its answers as sections into **the feature plan that already
exists** — creating no new artifact type.

| CoDev had | Canon | Why |
|---|---|---|
| `define-product` → brief | `frame` → sections in the feature plan | The questions survive: who has this problem, what changes for them, what success looks like. |
| `design-solution` → design + ADR | (same) | Becomes `## Shape` and `## Decisions`. A decision is recorded only where it was genuinely contested. |
| `plan-wave` → wave plan | dropped | Rolling-wave coordination for a team of two to six is machinery for a problem they don't have. An owner beside each step is enough. |
| `specify-project` → SPECIFICATION.md | dropped | A greenfield spec is a `frame` conversation with a wider scope, not a different kind of thing. |
| `launch-product` → launch plan | out of scope | Canon hands a reviewed PR to a human and stops. Deployment is deliberately somebody else's tool. |
| `testing-craft`, `technical-writing-style` | kept as-is | Reference knowledge with no lifecycle attached. Pure win — port them verbatim. |

**The boundary, in one sentence:** framing decides what is worth building
and what shape it takes; plan mode decides how one piece gets done — and
**the branch is the line between them**. Everything before the first branch
exists is framing. Everything after it is plan mode. A developer can hold
that.

**What keeps it from stiffening up again.** Three properties:

- **It asks only what's open.** If the opening message already says who
  it's for and what success looks like, `frame` says so and moves on.
  CoDev stated this rule well and then undercut it with mandatory stages
  every change had to pass through.
- **It has no gate.** No `Status: Accepted` line, no human acceptance
  recorded anywhere, no command that advances it. This is the biggest
  de-rigidifying move available: **exactly one thing in Canon needs
  approval — the branch plan — and Claude Code already ships the approval
  UI for it.** The feature plan is a document you read and edit like any
  other file in the repo.
- **It's invoked by shape, not by policy.** A change that fits in one
  branch never sees `frame` at all. It surfaces when the work obviously
  won't fit in one pull request, and a developer who wants to skip it just
  starts planning.

And the tripwire, stated now so it's checkable later: **if `frame` ever
produces its own file, or acquires an acceptance state, it has started
growing back into CoDev.** Those two things are what turned five good
skills into a pipeline.

## 07 · The spine — Where Claude Code actually drifts, and the hook that catches it

This table is the core of Canon. Each row is a specific, observed way an
agentic session loses the plot, and the deterministic mechanism that stops
it. Nothing here depends on the model remembering an instruction.

| Drift mode | Hook | What it does |
|---|---|---|
| **An approved plan evaporates** — it lands outside the repo and is swept in 30 days | `PostToolUse` `ExitPlanMode` | Saves the plan verbatim to `.canon/plans/<branch>.md` with a derived header. The one hook that makes plan mode's output durable, reviewable and readable by every other hook below. |
| Session starts cold; agent has no idea where the work stands | `SessionStart` | Derives position and injects it as `additionalContext`: branch, plan status, diff size, PR and check state. Replaces CoDev's `restore_position` hook *and* its state file. |
| **Compaction eats the plan** — the single biggest cause of long-session drift | `PreCompact` | Writes the thread note: the plan, decisions taken, what's been verified, what's open. `PostCompact` reads it straight back in. The plan survives the summariser because it was never only in the transcript. |
| Editing with no stated intent | `PreToolUse` `Edit\|Write` | No plan for this branch → `ask` with a reason. One prompt, once. CoDev's plan gate, minus the state lookup. |
| **Scope creep** — files touched outside the stated boundary | `PostToolUse` `Edit\|Write` | Compares the touched path against the plan's allowed paths *and its `## Non-goals`*. First departure: a note in `additionalContext`. Sustained departure: surfaced as a decision. Formats the file while it's there. |
| **Unverified claims** — "tests pass" asserted, not run | `Stop` | Runs the repo's own checks and reads the exit code. Red → exit 2, the turn continues with the failure attached. This is the verification loop, mechanised: the agent gets a self-check it cannot skip or misreport. |
| Self-approval by summary | `SubagentStop` | Captures the reviewer's verdict from the subagent's own output rather than from the main session's retelling of it. Matcher scopes it to `canon:reviewer`. |
| **Editing on `main`, or a redundant branch stacked on your own** | `PreToolUse` `Edit\|Write\|Bash` | Same gate as the missing plan, asked once: are we somewhere sensible, and is there a plan for it? Adopts a branch you made by hand rather than nesting under it. See §12. |
| Destructive git run casually | `PreToolUse` `Bash` | Guards `push --force`, `reset --hard`, `clean -fd`, branch deletion, and merge. Deliberately a short fixed list, not a config key. |
| Watching CI by polling | `monitors/` | Optional background monitor tails the check run and notifies when it lands, instead of the agent burning turns on `gh run watch`. |

> **One constraint to design around, verified against the hooks reference:**
> a `PreToolUse` hook returning `ask` degrades to *deny* when there's no
> interactive terminal. So in Slack, on the web, and in headless runs, an
> asking gate silently becomes a blocking one. Canon's gates must therefore
> know which mode they're in and return `deny` with an explanatory reason
> that tells the agent to surface the question as its final message — never
> a bare `ask`. This is exactly the kind of harness sharp edge Canon exists
> to absorb.

### The one thing Canon must be told

The `Stop` gate only works if Canon knows what this repository's check
actually *is*, and there is no reliable way to infer it. CoDev itself is the
example: the answer is `just test`, where `just` is a binary at
`.tools/just` that isn't on `PATH`, wrapping `bazel test` under a pinned
toolchain. Nothing in the tree announces that. A hook guessing `pytest`
would find it, run it, and report green while silently skipping mypy —
which is exactly the failure in §10's first use case, now with Canon's name
on it.

**Wrong-but-plausible is worse than absent**, because you start trusting
it. So Canon asks once, writes the answer down, and lets any individual
plan override it.

| Where | What | Scope |
|---|---|---|
| First run | Canon proposes what it inferred; you confirm or correct it in one exchange | Once per repository, not once per session |
| `.canon/config.json` | The answer, committed to the repo | Everyone working here, including CI-less clones |
| `verify:` in a plan header | Overrides it for that branch | One branch, where the work needs something different |

The key is deliberately not "the verify command" but **the command that
should pass before a turn ends** — a narrower and far more answerable
question for a repository with fast tests, a separate lint step and a slow
integration suite that needs data on disk. The slow half belongs to CI,
which §11 already establishes as a different layer with different
authority.

### No signal, no Canon

If no command can be established, Canon **stays inert** rather than running
without it. Not the gate alone — the whole plugin. That is a deliberately
opinionated call: a tool whose central promise is that nothing ships on the
agent's own word has no business operating where it cannot check that word.
Without a verification signal there is no self-check, and without a
self-check the agent is back to being trusted by assertion, which is the
condition Canon exists to end.

Two things keep this from being hostile. **The bar is a signal, not a good
one.** Canon requires *a* command that fails when the repository is broken
— for a young project, `python -c "import mypackage"` qualifies. A weak
signal is a weak guarantee and Canon says so, but a weak signal that is
named and improvable beats an absent one that nobody notices.

And **declining is not blocking.** Canon going inert means Canon is not
participating — it never obstructs the session, which continues exactly as
bare Claude Code. That keeps faith with the rule that every gate fails
open: the guardrail that cannot run gets out of the way rather than
standing in it.

### Notebooks, where the precondition turns out to be the gift

The target user works in `.ipynb` as often as in modules, so this is a
first-class question rather than an edge case — and three separate things
break. **Diffs**, because a notebook is JSON and a one-line semantic change
arrives carrying `execution_count` churn and re-serialised outputs,
sometimes megabytes of base64 image. **Size discipline**, because line
count stops meaning anything. And **verification**, because a notebook
repository frequently has no test suite at all.

The precondition above might seem to lock these repositories out. It does
the reverse. The command that should pass before a turn ends, for a
notebook repository, is `pytest --nbval-lax notebooks/` or a papermill run —
and **"it executes clean, top to bottom" is exactly the reproducibility
check this audience most needs and most often skips.** Hidden state and
out-of-order execution, which Canon could never address directly, fall out
of that single command for free. For the one group where correctness
failures surface as an unreproducible paper rather than an outage, the
precondition is the most useful thing Canon asks for.

Beyond that, **Canon treats a notebook as a file whose readable form the
repository must provide.** The ecosystem solved this already — `nbstripout`
as a git filter, or `jupytext` pairing each notebook with a `.py` percent
file that is what actually gets diffed. Canon's setup check notices
`.ipynb` tracked with neither configured and says so once, with the fix. It
recommends and never installs, the same rule as branch protection.

| Concern | What Canon does |
|---|---|
| Verification | Proposes `pytest --nbval-lax` when it sees notebooks, so the first-run question arrives with a working suggestion rather than a blank. |
| Review | Hands the reviewer the jupytext `.py` where one exists. Where neither tool is configured, extracts the code cells' source itself — about fifteen lines of standard-library JSON, `cell["source"]` where `cell_type == "code"` — and tells the reviewer what it is looking at, so `execution_count` churn is never filed as a finding. |
| Size | Counts **code cells changed** rather than lines when the file is `.ipynb`. Deterministic, and it makes the small-change discipline measurable again. |

That cell extraction is the single place in Canon that knows what a
notebook is, and it is deliberate rather than an oversight. The purer
position — decline to review until the repository configures a tool —
keeps the recommend-don't-reimplement line completely unbroken, but it
makes Canon precious about a file format its users open every day, and
useless on day one in a repository nobody has set up yet. Fifteen lines
buys a great deal of that back.

What Canon still never does: install `nbstripout`, configure `jupytext`,
strip outputs, rewrite a notebook, or render a diff. Those are repository
configuration or they are machinery, and neither is Canon's.

## 08 · The server — Five tools, zero stored state

| Tool | Returns | Derived from |
|---|---|---|
| `canon_position` | Where the work stands and the single next step, in plain language plus structured fields | branch name, `base..HEAD`, plan status line, `gh pr view`, check runs, review state |
| `canon_plan` | Read the saved plan for this branch, or the feature plan above it | a markdown file in the repo, git-tracked; written by the `ExitPlanMode` hook, not by this tool |
| `canon_evidence` | Whether this commit is green, and where that was established | `gh run list --commit <sha>` for a pushed commit; a local re-run for an unpushed one. **Stores nothing** — see below. |
| `canon_review` | Which reviewers this diff calls for, and the last verdict against this HEAD | changed paths matched against risk surfaces; `SubagentStop` captures |
| `canon_ship` | Whether this is ready for a human, and precisely what's missing if not | the three invariants, evaluated; no separate readiness record |

### Why there is no evidence store

An earlier draft gave Canon a gitignored cache of test results keyed by
commit SHA. It was defensible — a tree at a SHA never changes, so such a
memo can be *lost* but never *wrong*, unlike CoDev's `base_snapshot`, which
described a moving target. It was still the wrong call, because it answered
two different questions with one store.

**"Can this turn end?"** is answered by the `Stop` hook running the check,
and the answer is consumed inside that hook invocation. Nothing needs to
outlive it. **"Is this branch actually green?"** is answered by CI on the
pull request head — content-addressed by the same SHA, visible to
everyone, and already the thing a reviewer looks at. Canon keeping a
parallel record of that would be rebuilding CoDev's mistake at a smaller
scale.

The interval between them — pushed, CI not finished — is not a gap to
paper over. It is a true state of the world, and "CI is still running" is
the honest answer rather than a cached guess. So the rule is: **Canon may
cache only a pure function of an immutable input, and only when
recomputing costs more than the cache risks.** Nothing currently qualifies
on the second clause, so Canon stores nothing.

Note what's absent: no `start`, no `advance`, no `record`, no `close`, no
`reopen`, no `waive`. Those are all verbs that mutate a lifecycle, and
Canon has no lifecycle to mutate. The only tool that writes anything is
`canon_plan`, and what it writes is a file the developer can read, edit and
revert like any other.

`canon_position` is the one the agent calls constantly — at session start,
after each gate, whenever it's unsure. It is CoDev's navigator idea, which
was sound, decoupled from the state machine that made it unreliable.

## 09 · Developer experience — One dial covers Slack, the IDE and pair programming

Slack, the IDE extension and a terminal pair session don't differ in *what*
Canon should enforce. They differ in **how much the developer can be
asked, and when**. That is one axis, not three workflows — so Canon
exposes exactly one enumerated setting, validated to these three literals
and nothing else.

| Mode | Fits | Behaviour at a gate |
|---|---|---|
| `pair` | Terminal or IDE, someone watching | Ask at every boundary. Plan approved in plan mode as usual, review verdict read back before proceeding, next step named each time. |
| `solo` *(default)* | IDE, working alone | Ask only at real gates: missing plan, red verification, scope departure, ready-for-human. Everything routine happens silently. |
| `async` | Slack, web, headless, cloud | Never blocks on a question. A gate that would ask instead *stops the turn* and posts the question as the final message — which, in Slack, is exactly the right interaction anyway. |

Canon picks the default by detecting whether a terminal is attached, and
the developer can pin it. The important property is that **the same hooks,
the same skills and the same reviewer run in all three** — only the
interaction changes. That's what makes the guidance explainable: there is
one workflow, presented at three volumes.

The other half of DX is that Canon should be *legible while running*. Every
gate that fires says, in one sentence, what it checked and why it cared. A
developer who's never read this document should be able to infer the whole
model from the messages Canon emits during one real change.

## 10 · Three use cases — The same work, with the harness bare and with Canon on top

The baseline here is **Claude Code as it ships** — capable, and already how
most of this work gets done. Canon's claim isn't that the bare harness
fails; it's that it forgets, over-reaches and over-claims in three
specific, recurring ways.

### Case 1 · the everyday one — A bug fix that takes an afternoon

Duplicate dataset slugs are silently overwriting each other. Two files to
change, one regression test. You've done a hundred of these.

**Without Canon.** You describe the bug. Claude finds it, fixes it, adds a
test, and reports: *"All tests pass."* It ran `pytest tests/slugs/`. The
repo's actual check is `just test`, which also runs mypy — and the fix
introduced a type error. You find out eleven minutes later from a red CI
badge, in a different mental context, and have to reload the whole problem
to fix two lines. Separately, while it was in there, it tidied a
neighbouring helper. Harmless, probably. It's in the diff now, and
reviewing it is your problem.

**With Canon.** Same conversation, in plan mode. You approve a short plan;
its `## Non-goals` says *"not touching the export helpers"* and its
`## Verification` says `just test`. Claude edits. The moment it opens the
export helper, the scope check notes the departure and it backs out —
before the edit is in your diff. It tries to end the turn. The `Stop` hook
runs `just test` itself, gets the mypy failure, and the turn simply
continues with the error attached. Claude fixes it and ends the turn green
— and the green is recorded against that exact commit.

**What you actually gain.** You never context-switch to a CI failure you
could have caught locally, and you review two files instead of three. The
claim "tests pass" stops being something you have to take on trust — not
because Claude is less trustworthy, but because nobody should have to audit
a sentence when an exit code is available.

### Case 2 · the planned one — A feature you build over six weeks, around teaching

Public permalinks for datasets: a slug model, a resolver, and a migration.
Three pull requests. You'll start it this week, then not touch it for a
month when the semester starts.

**Without Canon.** Day one goes well. Plan mode produces a genuinely good
plan; you approve it and build the slug model. The plan is now in
`~/.claude/plans`, and in a transcript. Day three, a fresh session. You
re-explain the feature. Claude proposes a resolver that doesn't match the
slug model's assumptions, because it never saw the reasoning — only the
code. Five weeks later you come back. The transcript is gone, the plan
file was swept at thirty days. You read your own code to work out what
you'd decided and why you rejected the alternative. You can't remember. You
pick again, differently, and the migration now contradicts the resolver.

**With Canon.** You describe the idea. `frame` asks the two things you
hadn't settled — what happens to existing slugs, and whether old URLs must
keep working — and skips the rest, because you'd already said who it's
for. The feature plan lands in the repo with three `steps:`. Each step gets
its own branch and its own plan mode session, and each saved plan carries
`parent:` pointing back at the feature plan. Step two opens knowing what
step one decided. Five weeks later you open the repo. `SessionStart` tells
you: step two of three, branch merged, step three not started. The
reasoning you'd forgotten is in `docs/decisions/0007-slug-collision-strategy.md`,
which Claude wrote when step one merged — including the alternative and why
it lost.

**What you actually gain.** Returning to your own work stops being
archaeology. The thing that survives the gap isn't the code — you can
always read code — it's the *intent and the rejected alternatives*, which
is exactly what a transcript loses and a repository keeps. For work that
goes quiet around teaching and funding cycles, this is the difference
between resuming and restarting.

### Case 3 · the dangerous one — A migration that can quietly lose data

Splitting a results table, backfilling four years of experiment records.
It'll touch a dozen files. If it's subtly wrong, nothing breaks loudly — a
paper does, eighteen months from now.

**Without Canon.** Claude does competent work. The tests pass, because the
tests were written against the schema it just changed. You review 600
lines at seven in the evening. You read the migration carefully and skim
the backfill, which is where the off-by-one in the date window is. There's
no second reviewer — there are two of you and your colleague is at a
conference. The risk here was never that Claude is careless. It's that
**the amount of scrutiny a change gets is set by how tired one person is**,
and a diff that touches persistent data looks exactly like a diff that
doesn't.

**With Canon.** Nothing about the conversation changes — but `canon_review`
reads the diff, sees a schema change and a data backfill, and dispatches
the risk reviewer alongside the ordinary one. You didn't select them and
there's no waiver to write; the diff decided. The risk reviewer runs
read-only in a fresh context, with the plan's `## Non-goals` so it doesn't
report deliberate omissions as gaps. It flags the backfill window. Claude
fixes it; the `Stop` hook re-verifies; the reviewer runs again. What
reaches you is a smaller, already-corrected diff with a written verdict
attached — and the decision record explaining why the table was split this
way rather than the other.

**What you actually gain.** Scrutiny becomes a property of the change
rather than of your evening. This is the case where a second human reviewer
genuinely may not exist, and Canon's honest answer is not to pretend the
machine replaces one — it's to make sure the human who *is* there spends
their attention on a diff that's already been read carefully once.

## 11 · End to end — Idea to shipped, with nothing left out

One feature, all the way through, including the parts that usually go
unmentioned. **you** is the developer, **claude** is the session, **canon**
is a hook or tool firing on its own, and **outside** is CI or another
person.

**Frame · once per feature**

- **you** — "We need public permalinks for datasets, so people can cite them."
- **claude** — Reads the repo before asking anything: the existing URL
  scheme, the dataset model, how tests are run.
- **canon (frame)** — Surfaces the two questions that are actually open:
  what happens to existing slugs, and whether old URLs must keep resolving.
  Skips the four you already answered. No form, no gate, no acceptance
  line.
- **claude** — Writes `.canon/plans/features/public-permalinks.md` — why,
  success, non-goals, shape, decisions, and `steps:` listing three
  branch-sized pieces.
- **you** — Read it, reorder two steps in your editor, move on. It's a
  file, not a ceremony.

**Plan · once per step**

- **claude** — Branches for step one only, then enters plan mode and reads
  the code properly.
- **canon (plan skill)** — Seeds the headings while the draft is being
  written, so `## Non-goals` and `## Verification` are there to review
  rather than requested afterwards.
- **you** — Comment inline on the Non-goals section, tighten one line,
  approve — the normal plan mode flow, untouched.
- **canon (ExitPlanMode)** — Saves the approved plan verbatim to
  `.canon/plans/permalinks-slug-model.md` and derives the header: base SHA,
  allowed paths, `verify: just test`, `parent:`.

**Build**

- **claude** — Implements. No subagent — this is judgement work, and
  handing it off would cost the context that makes it good.
- **canon (PostToolUse)** — Formats each file as it's written, and checks
  the path against allowed scope and Non-goals. Silent while inside the
  boundary. *Quality layer one: instant, cosmetic, no authority.*

**Check · the turn cannot end red**

- **canon (Stop)** — Runs `just test` — lint, types, tests. Mypy fails.
  Exit 2: the turn does not end, and the failure is handed back.
- **claude** — Fixes the type error in the same turn, while the problem is
  still loaded.
- **canon (Stop)** — Green — the turn ends. Nothing is written down: the
  answer was needed inside this hook invocation and nowhere else. *Quality
  layer two: end of turn, blocks the turn, one machine.*

**Review · machine first**

- **canon (canon_review)** — Reads the diff: no auth, no persistent data,
  no migration. One reviewer, not five. Nothing to select, no waiver to
  write.
- **claude** — Dispatches `canon:reviewer` — read-only, fresh context,
  given the diff, the plan and its Non-goals, and nothing of the writer's
  reasoning.
- **canon (SubagentStop)** — Captures the verdict from the subagent's own
  output: `CHANGES REQUIRED`, one finding. Not from the main session's
  retelling of it.
- **claude** — Addresses the finding. `Stop` re-verifies; the reviewer runs
  again and returns `READY`. Two attempts at one root cause is the cap — a
  third stops and asks you.

**Ship**

- **canon (canon_ship)** — Checks the three invariants: plan satisfied,
  evidence green at *this* HEAD, independent verdict present. Then: did
  this branch make a recordable decision with no record? Yes — the slug
  collision strategy.
- **canon (decide)** — Drafts `docs/decisions/0007-slug-collision-strategy.md`
  from context already in the session: what was chosen, what was rejected,
  why. Committed into this branch.
- **claude** — Opens the PR. Body is the plan's approach, its non-goals,
  and the exact verification that ran — not a summary of the diff, which
  the diff already is.

**CI · the authoritative check**

- **outside (Actions)** — The full matrix runs: every Python version, every
  OS, the slow integration tests the `Stop` hook skips. *Quality layer
  three: minutes, blocks the merge, all platforms.*
- **canon (monitor)** — Notifies the session when checks land, instead of
  Claude burning turns polling `gh run watch`.
- **claude** — Windows leg fails on a path separator. **Bounded repair: two
  attempts.** Fixed on the first; had it not been, Claude stops and reports
  rather than grinding.

**Human review · the only real gate**

- **claude** — "Step one is ready. Green on all legs, reviewed, one
  decision recorded. Asking Hannah to look at it."
- **outside (colleague)** — Reviews a small PR that has already been read
  carefully once, with the reasoning attached. Leaves two comments.
- **claude** — Addresses both. Every fix re-runs the `Stop` gate, so the PR
  is never green-by-assertion after a change.

**Land**

- **outside (colleague)** — Merges. **A human merges, always** — Canon
  opens pull requests and never closes them.
- **canon (canon_position)** — Recomputes from scratch: step one merged,
  step two has no branch. Nothing was stored, so nothing can be stale, and
  there is no bookkeeping commit to go wrong.
- **claude** — "Step one landed. Step two is the resolver — want me to
  branch and plan it?"

### How the three quality layers fit together

The same checks run at three latencies, and that layering is deliberate
rather than redundant.

| Layer | When | Scope | Authority |
|---|---|---|---|
| `PostToolUse` | As each file is written | Format the one file just touched | None — cosmetic, never blocks |
| `Stop` | End of every turn | The repo's own check command, one machine | Blocks the turn ending |
| CI | On the pull request | Full matrix, every platform, slow tests | Blocks the merge |

Each layer is cheaper and earlier than the one below it, and **none of them
takes the agent's word for anything**. The `Stop` hook exists so CI is not
the first time you learn something is broken; CI exists because the `Stop`
hook runs on one machine with one Python version. Neither replaces the
other, and the `PostToolUse` formatter is there purely so neither of them
ever fails for a reason as trivial as whitespace.

### What isn't in the timeline, on purpose

No state file is written or read. No round is opened, closed, advanced or
reopened. No coverage dimension is waived. No specialist is selected by a
human, and no dispatch is authorized. No status line is set to `Accepted`.
No bookkeeping commit lands — which means nothing in this sequence can trip
a drift check, because there is no drift check, because there is no stored
snapshot to drift from.

For comparison, the same feature through CoDev involves ten steps per pull
request, of which **four exist only to maintain CoDev** — and, on the
evidence in §01, roughly two thirds of rounds then needed a hand-written
reopen to get past the machinery's own commits. Every step above is either
you deciding something or a fact being established. That is the whole
difference.

## 12 · Git and GitHub — What Canon may touch, and the branch it must not create

One test decides the whole boundary: **can a human undo this in one click
without losing work?** Reversibility, not importance.

| Operation | Canon | Why |
|---|---|---|
| `git switch -c` | yes | Cheap and reversible — but subject to the posture rules below, which are the part that actually matters. |
| `git commit` | yes | Small and frequent. Recoverable from reflog. See the no-self-commits rule below. |
| `git push` (own branch) | yes | Publishing a branch nobody else is on costs nothing to undo. |
| `merge`, `rebase` onto a shared branch, `push --force`, `reset --hard`, branch delete, tag | **never** | Each either rewrites shared history or destroys work. A fixed list in the `PreToolUse` git guard, not a config key. |
| Open a pull request | yes | It *is* the deliverable, and closing one is a single click. |
| Merge or close a pull request | **never** | The only real gate in the whole system. Canon opens pull requests and never closes them. |
| Read PR comments, reply to them | yes | The correction loop needs both. Posting an *approving* review is never Canon's. |
| Create issues, labels, milestones | **no** | Passes the letter of the test and fails its spirit: an issue creates an obligation someone has to tend. |
| Read an issue, link a PR to it | yes | If the work started from an issue someone filed, reference it. Reading and linking, never creating. |

### Who approves the merge — nobody Canon names

CoDev required an approval *distinct from the task owner*, then needed a
waiver command for repositories where no second person exists, and
accumulated 59 waivers. It also sat against the intended workflow, which
ends by handing the change back to the developer who owns it. Both can't be
the final word, and CoDev never chose.

The tangle comes from "review" doing three jobs at once — who *reads* the
code, who *authorizes* the merge, and who is *accountable* for it. Tying
authorization to "not the owner" is Google's model, correct where
authorship and review are separable roles. In a group of two it yields one
of two things: a colleague approving without really reading, which is
**worse than no gate because it manufactures false assurance**, or a
waiver — the gate conceding it doesn't apply.

**So Canon has no review-authority gate at all.** The three jobs are
answered in three different places:

| Question | Answered by | Canon's part |
|---|---|---|
| Who reads the code? | The reviewer subagent, then a human | Dispatches it, captures the verdict. **The verdict is evidence, never approval** — a fact about the code, like a test result, authorizing nothing. |
| Who authorizes the merge? | A human, and **GitHub branch protection** decides which | None. Canon ends at "this is ready, and here is the evidence." |
| Who is accountable? | The developer who owns the work | Names them in the handoff, reading `CODEOWNERS` where one exists. |

This dissolves the question rather than answering it, and it puts the
policy where policy already lives. Canon has no business reimplementing
GitHub's review rules — the same reason it recommends a branch-protection
rule below rather than setting one. **A solo repository stops being a
per-change waiver and becomes a protection rule requiring zero approvals:**
one visible, one-time, honest statement instead of 59 justifications.

The cost, stated plainly: Canon ships enforcing no independent review, and
a team that never configures branch protection gets none. That is a real
weakening against CoDev. It is the right trade because Canon checks for
protection at setup and recommends it, because an unenforced prose gate is
worse than an honest absence, and because the reviewer subagent runs either
way — so every change is still read by something that is not its author.

### Canon never authors a commit of its own

This one is a direct lesson from §01. Every CoDev escalation that read
*"…its own auto-commit lands one commit past the `--head` value passed to
it"* came from a commit CoDev made *about itself*. So: no
`chore(canon-bookkeeping)`, ever. The saved plan and the decision record
ride inside the commit that contains the work they describe. A workflow
tool that never commits on its own behalf cannot be confused by its own
history.

### Why no issues, when CoDev created one per task

CoDev created an issue for every task, then needed a mechanical linkage
gate to keep them attached and a `relink` recovery command for when they
came apart — two pieces of machinery to maintain a second source of truth
for something the pull request already tracked. For a group of two to six
people that is pure overhead. Canon reads issues and links to them; it
files none.

### The branch problem, which is really two problems

Both of these are ordinary Claude Code failures, and both are worth
naming, because the fix is the same check in two directions. The rule
underneath: **branch topology belongs to the developer.** Creating a branch
is cheap but not free — an unnecessary one fragments your own picture of
where your work lives, and it's a small mess you clean up later.

**A. On the default branch → branch before editing.** Work silently
beginning on `main` is the more dangerous of the two, because you often
notice at commit time rather than edit time. Canon derives the protected
branch from the remote's default rather than guessing the name, and the
gate fires at the *first edit*, not the first commit. A genuinely
trunk-based repository turns it off with a boolean — the one thing here
worth making configurable, because it's a real binary and some repos
legitimately commit to trunk.

**B. On a branch you made yourself → adopt it, never nest under it.** The
fix is a rule rather than a heuristic: **a branch the developer created by
hand is a statement of intent.** If the current branch is not the default
branch, Canon works on it and writes the plan *for* it. It does not create
a child branch. The `PreToolUse` git guard catches `switch -c` and
`checkout -b` attempted from a non-default branch and asks what you meant,
rather than letting the agent act on the impulse.

The one legitimate exception is a genuinely separate change — step two of
a feature while step one is still open. There Canon asks explicitly: stack
on this branch, or branch from the default? It never assumes.

Both live in the same gate as the missing-plan check, deliberately: **one
prompt at the first edit, asking one question** — are we somewhere
sensible, and is there a plan for it? Two separate interruptions for what
is one moment of setup is exactly the kind of narrated ceremony this whole
document exists to avoid.

Canon also reports a branch that looks wrong — cut from a stale base, or
named against the repo's convention — and **does not fix it**. Renaming or
rebasing someone's branch is not one-click-undoable in the only place that
counts, which is their head.

On protecting `main` properly: a GitHub branch-protection rule is the real
answer and Canon should *recommend* one, not set it. Changing repository
settings fails the reversibility test outright, and it's an admin action
with consequences for everyone rather than for this session.

### Keeping Claude out of the authorship

Claude Code attributes itself by default — a `Co-Authored-By` trailer on
commits and a generated-with line in pull request bodies. For scientific
software that is not a cosmetic annoyance. Authorship is a claim these
repositories make formally, in `CITATION.cff`, in `AUTHORS`, and eventually
in a paper's author list, and an AI listed among them is a real problem
rather than a tidiness one. It also asserts co-authorship of a kind that
copyright guidance does not support.

Canon's documentation carries a short **Attribution** page with three
layers, because no single one of them is currently sufficient.

**The setting, first — and note the current key.** `includeCoAuthoredBy`
is deprecated; the current form is `"attribution": { "commit": "", "pr": "" }`
in `settings.json`. A plugin cannot ship this for you (plugin
`settings.json` accepts only `agent` and `subagentStatusLine`), so Canon's
docs tell you to set it and Canon's health check tells you if it isn't set.

**The hook, second — this is Canon's own contribution.** There are open
reports of the attribution settings not being fully respected, with a
session trailer still reaching commits and PR bodies. So the `PreToolUse`
git guard, which is already inspecting `git commit`, strips any
AI-attribution trailer it finds. Deterministic, and it does not depend on a
setting behaving.

**The prose, third**, for everything the other two can't see: a PR body
written through `gh pr create --body`, a changelog entry, a docstring
byline, a footer in a generated document.

```markdown
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
```

### One open mechanism

Canon drives GitHub through the `gh` CLI rather than a GitHub MCP server,
because `gh` is already authenticated on your machine and a server means a
second credential story. The gap: `gh` may not be authenticated in a Slack
or cloud-sandbox session. `async` mode therefore needs a checked fallback —
establish it early and say so plainly — rather than discovering it at the
moment it tries to open the pull request.

## 13 · Method — Build it the way the Claude Code team builds Claude Code

Three practices from Anthropic's public record, adopted as rules rather
than aspirations.

**Start at zero and earn every line back.** The Claude Code team deletes
the system prompt each model generation and restores only lines that prove
themselves by ablation — over 80% removed for Opus 5 with no measured
quality loss. Canon's rule: **no instruction line ships without an eval
that fails when you remove it.** `claude plugin eval` exists for precisely
this and runs each prompt with and without the plugin loaded. CoDev's 34 KB
is what happens without this rule; it is also the reason CoDev's
instructions kept needing hardening ADRs.

**Give the model a slightly-too-hard task and a way to check itself.** The
pattern behind every successful long-running agent run is the same: a hard
task plus an unambiguous verification signal. Over-specifying steps is the
documented primary failure mode, and experienced engineers do it most. So
Canon's plan header records the *outcome* and the *proof*, and Canon never
asks the plan body to enumerate steps it doesn't need. The `Stop` hook is
the verification signal, made impossible to skip.

**Treat the model as an empirical subject, not a system to configure.**
Behaviour shifts each generation; harnesses and evals saturate within a
few. Canon should therefore be small enough to re-derive cheaply, and
should re-run its evals on each model release with an explicit question:
*which of our rules has the model outgrown?* Anything CoDev learned that is
now scar tissue from an older generation gets deleted, not ported.

> **Where the videos land.** The Cherny talk supplies the deletion
> discipline and the verification-is-the-bottleneck framing above. The
> intent-driven-development demo supplies the other half: the developer's
> job moves to *stating intent and reviewing outcomes*, roughly inverting
> the old 90/10 split between writing and reviewing. The saved plan is the
> artifact that makes intent explicit and reviewable; the reviewer subagent
> and the `Stop` hook are what make reviewing outcomes tractable at that
> volume. Both videos point at the same conclusion — the leverage is in
> specifying and verifying, not in choreographing the steps in between.

## 14 · Build order — Four phases, each shippable on its own

Genuinely sequential: each phase depends on the one before it, and each is
shippable on its own. **This document and CoDev's recorded experience are
the specification** — Canon is built to them rather than discovered by
using it. Validation is the test suite and, from Phase 3, the eval corpus;
it is not a round of exploratory dogfooding, because the design questions
those would answer have already been answered here.

**Phase 0 — The thread.** Plugin skeleton and manifest. `canon_position`
and `canon_plan`. The `plan` skill. Four hooks:
`PostToolUse:ExitPlanMode` to save the approved plan, `SessionStart`
injection, `PreCompact`/`PostCompact` thread note, and the `Stop`
verification gate. First-run setup comes with it, and is the first thing a
developer meets: **one question, asked once** — what command should pass
before a turn ends? Until it's answered Canon stays inert, so this is not a
step that can be deferred to a later phase. This is the smallest thing that
fixes the biggest problem: a session that survives compaction with its
intent intact, and cannot end a turn on an unverified claim, is already
substantially less drifty than the bare harness — with no reviewer, no PR
flow and no state of any kind. *Ship it.*

**Phase 1 — The second pair of eyes.** `reviewer` subagent, `canon_review`,
`canon_evidence`, `SubagentStop` capture, and the scope-departure half of
`PostToolUse`. Port `review-change` and `testing-craft` from CoDev largely
intact — **copied and then forked**, never kept in sync. Both projects are
BSD-3-Clause with the same author, so copying is unencumbered, and a shared
source would mean maintaining a bridge to a project that is no longer being
developed. Invariant III becomes real here: the first verdict that the main
session did not write about itself. *Ship it.*

**Phase 2 — Shipping.** `canon_ship`, the `ship` skill, the git guard
hook, risk-surface detection and the `risk-reviewer` agent. The three
interaction modes, with `async` tested against a real headless run rather
than assumed. The `decide` skill lands here too, since "at merge" is only
meaningful once there is a merge path. The `frame` skill and the feature
plan follow — by now the single-branch loop works end to end, so
multi-step features are the natural next shape rather than a speculative
one. The end state is the handoff Canon exists to produce: a small PR with
green evidence at HEAD, an independent verdict attached, and a named human
asked to look at it. *Ship it.*

**Phase 3 — Ablation.** Build the `claude plugin eval` suite, then
**delete instructions until something fails**. Every line that survives is
a line with a failing eval behind it. Publish the suite with the plugin so
the next model generation can re-run it. Deliberately last, and
deliberately not optional. Without it, Canon is on a straight path back to
34 KB. *Gate on it in CI.*

## 15 · Settled

Each of these was open when this document was first written, and each was
named rather than papered over — because otherwise they get decided by
whichever code is written first, which is how CoDev accumulated its
superseding ADRs. They are recorded here with their answers so the
reasoning survives the decision.

✓ **Who is the independent reviewer in a group of two?** Nobody Canon
names. The AI verdict is evidence, never approval; merge authority is a
human chosen by GitHub branch protection, not by Canon. A solo repository
is a protection rule requiring zero approvals, not a per-change waiver. See
§12.

✓ **Where does evidence live between turns?** It doesn't. The `Stop`
hook's answer is consumed inside the hook; CI's answer is already keyed by
the same SHA and lives in GitHub. Canon stores nothing. See §08.

✓ **How does Canon discover the verification command?** Asked once on
first run, written to `.canon/config.json`, overridable per plan. And it is
a **precondition**: with no signal, Canon stays inert rather than operating
unverified. See §07.

✓ **What does Canon do about notebooks?** Requires the repository to
provide a readable form — `nbstripout` or `jupytext`, recommended and
never installed — counts code cells rather than lines, and extracts cell
source itself when neither is configured. The verification precondition
turns out to be the most valuable thing Canon asks a notebook repository
for. See §07.

✓ **Does CoDev continue?** Its fate is open, but for now it **remains
stale while Canon becomes the main project** — not archived, not ended,
simply not under active development. Phase 1 may therefore copy its skills
and fork them freely rather than sharing a source, and its multi-platform
port obligation lapses: Canon targets Claude Code alone. Its 45 ADRs stay
useful as prior reasoning to read, not as decisions to port.

---

*Canon · plan v1 · 13 September 2026 · Evidence: CoDev @ f5701c7 · No code
written at time of writing*
