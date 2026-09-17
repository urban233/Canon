# 0006. Layer one reports a repository-named check rather than formatting the touched file

## Context

`docs/plan.md` §11 sets out three quality layers at three latencies. Its
table gives the first one a scope and an authority:

| Layer | When | Scope | Authority |
|---|---|---|---|
| `PostToolUse` | As each file is written | Format the one file just touched | None — cosmetic, never blocks |

§07's spine table says the same thing in passing: the scope-departure hook
"formats the file while it's there."

That layer was never built. `check_scope.py`'s docstring records why, and
records it as deferred rather than decided: "hooks are stdlib-only and run
via bare `python3`, with no guaranteed access to a resolved formatter
binary; that's a separate decision, not a bolt-on to this one."

The cost of the gap then showed up. In one session three pull requests
failed CI on `fmt_check` and nothing else — build, test, lint, typecheck,
`sync-check` and `validate-plugin` green on all three. §11's own
justification for layer one is that it exists "purely so neither of them
ever fails for a reason as trivial as whitespace", and that is exactly
what happened, three times, in the repository that wrote the sentence.

This is the separate decision `check_scope.py` deferred.

## Decision

Layer one ships as `fast_check.py`: a `PostToolUse` hook that runs a
command the **repository names**, on the **whole repository**, and
**reports** the result as `additionalContext`. It does not format
anything, and it does not act on the touched file in particular.

The command is the optional `check` key in `.canon/config.json`, a sibling
of `verify`. Its absence turns the layer off and is not an error.

Three points where this departs from §11's literal text:

**Canon runs a command; it does not format.** A hook is standard-library
only and runs via bare `python3`, so it can resolve no tool. In this very
repository `ruff` and `pyrefly` exist only inside Bazel's pip hub, with no
binary on `PATH` at all — `which ruff` is empty. A hook that shells out to
whatever it can find is the failure `_common.py`'s docstring was written
against: CoDev's hooks resolved a CLI on every invocation and found
nothing to run 508 times out of 1,112. Naming the command in config is the
same shape `verify` already uses, and it is the only shape that works in
the repositories Canon is installed into, which do not have Canon's
toolchain.

**Repository-wide, not the touched file.** `pyrefly` cannot check one file
— `tools/pyrefly_check.sh` passes no paths at all, because it has to see
the whole tree to resolve the cross-file `import _common` every hook does.
A per-file contract would have excluded typechecking from a layer whose
whole purpose is catching the cheap failures early.

**Reported, not fixed.** §11 says "format", which implies mutation. A hook
that rewrote a file the agent had just written would be editing the
developer's change without being asked, and `PostToolUse` fires after the
edit, so it could not have prevented anything either way. Reporting keeps
the authority §11 assigns the layer — none.

## Consequences

The failure mode §11 named is closed, for any repository that sets
`check`. Canon's own is `bazel test //:fmt_check //:lint //:typecheck` —
cached targets that exclude the test suite entirely.

**A repository that does not set `check` has no layer one.** Nothing
infers the command, deliberately: there is no first-run question for it to
be confirmed against the way `verify`'s is, and §07 is explicit that a
wrong-but-plausible answer nobody was asked about is worse than none. The
first-run message mentions the key so it is at least discoverable, but a
repository that ignores it simply behaves as Canon did before this
existed.

**A timeout reports nothing.** A `check` and a `verify` are usually the
same build tool, and a build tool serialises per output base, so a timeout
is more likely to be this hook waiting on a lock another Canon gate holds
than a real regression. The two are indistinguishable once reported, and
an advisory layer that cries wolf is one a developer learns to ignore.
Silence costs one turn's earliness; layer two still blocks the turn and CI
still blocks the merge.

**§11's table is now wrong about this row, and stays that way.** The plan
document is the specification and is not edited to match the code — the
same course `0003` and `0005` took. A reader of §11 alone will expect a
per-file formatter and find a repository-wide reporter; this record is
where that reader is meant to land.

The alternative was to keep deferring. It was rejected on the evidence:
the layer's absence has now cost three pull requests in one session, and
the reasons it was deferred are reasons to build it differently, not
reasons not to build it.
