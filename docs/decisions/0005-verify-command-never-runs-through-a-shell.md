# 0005. The verify command never runs through a shell

## Context

`stop.py`'s `_run_verification` and canon_mcp's `_run_local_check` both
run the configured `verify` command the same way: `subprocess.run(shlex
.split(command), ...)`, with no `shell=True` and no `sh -c`. That choice
is argued at length in `_config.py`'s `shell_metacharacter` docstring
and in `stop.py`'s `_first_run_reason`, but both are function- and
message-level prose, not a record -- and the choice has a real, easy
alternative that a later contributor will reach for.

The failure mode that makes the alternative tempting: `shlex.split`
does not understand shell operators at all. `ruff check . && pytest`
becomes `['ruff', 'check', '.', '&&', 'pytest']`; `ruff` receives `&&`
as a literal path argument, exits non-zero for a reason that has
nothing to do with the repository, and the `Stop` gate reports that as
a failing check forever, with no way for the developer to tell "the
config is broken" from "the tests are red" apart from reading the exact
error text closely. An independent review of the fix for this
(`plugins/claude/hooks/_config.py`'s `verify_command_problem`) also
turned up several ways the detector under-caught the same class of
command -- `pytest 2>&1`, `ruff check . & pytest`, `pytest >> log`, and
others -- each one a fresh reminder of how much surface a real shell's
operator grammar has, and how easy it is to miss a piece of it.

The obvious fix for "the detector missed one" is `subprocess.run(command,
shell=True, ...)` and skip detecting metacharacters at all -- let a real
shell parse the command the way the developer expects. That is exactly
the alternative this record exists to rule out.

## Decision

Canon never runs the configured verify command through a shell.
`shlex.split` plus a validator that refuses a command it cannot run
correctly (`verify_command_problem`) is the whole mechanism; there is no
`shell=True` fallback, not even for a command the validator has
approved, and not even as a documented escape hatch for a repository
that needs one.

Two reasons, not one:

**A compound command is ambiguous evidence, which is what the `Stop`
gate exists to eliminate.** `docs/plan.md` §07 is explicit that
Invariant III's entire point is that nothing ships on the agent's own
word -- the harness checks a claim, deterministically. `ruff check . &&
pytest` run through a real shell can fail because `ruff` failed, because
`pytest` failed, or (with `set -e` unset, the default) can report a
non-zero-but-misleading exit code depending on which half ran. "Which
half was red" is exactly the kind of question a human has to go
re-derive by hand, defeating the purpose of an automated gate that is
supposed to answer it for them. A single named command has one exit
code and one meaning; a chain does not, unless someone writes the chain
into a script that decides how partial failure is reported -- which is
the next paragraph.

**Running a string through a shell means Canon executes text a
developer wrote into a JSON config file or a plan header as code, with
no further review.** `.canon/config.json` and a plan's `verify:` line
are both things Canon reads back and acts on automatically, every
`Stop`. `shlex.split` plus a strict validator treats that string as
data -- an argv list, checked before it is used. `shell=True` treats it
as a program, interpreted by `/bin/sh` with the full grammar of command
substitution, redirection, and chaining available to it. That is a much
larger trust boundary to hold open for a string whose only stated job is
"name the check to run," and it does not buy anything `shlex.split`
does not already provide for the actual use case: running one command.

The fix for "the developer's real check is a sequence" is not a wider
grammar. It is what `_first_run_reason` and `verify_command_problem`'s
message already say: wrap the sequence in a recipe or script -- a
Justfile recipe, an npm script, a shell script committed to the
repository -- and name that single command instead. That script is
still free to use `&&`, pipes, or anything else a shell provides; the
chaining happens inside a file the developer wrote and reviewed, not
inside a string Canon interprets on their behalf every turn. Canon
proposes that wrapper and refuses to write it, the same line it already
holds on `nbstripout` and on branch protection (see this repository's
recommend-don't-reimplement rule, argued in `docs/plan.md` and echoed in
`session_start.py`'s notebook section) -- editing a repository's build
configuration is not Canon's job even when the fix is obvious.

## Consequences

`shell_metacharacter` and `verify_command_problem`
(`plugins/claude/hooks/_config.py`, mirrored in
`src/canon_mcp/canon_mcp/_config.py`) have to be right, not merely
plausible, because there is no shell fallback catching what they miss --
an under-caught compound command is not degraded gracefully into "a real
shell runs it correctly anyway," it is silently mis-split the way the
original defect was. That is why the detector's rule is "every character
in a token is an operator character," not an exact-match list: a
narrower rule under-catches, and under-catching here has no safety net.

A verify command genuinely cannot use shell features directly -- no
inline `&&`, no `$()`, no output redirection written straight into
`.canon/config.json`. Every one of those is still available inside a
wrapper script, which is the intended and only path for a compound
check. This is a real constraint on what `verify:` can say, accepted
deliberately in exchange for a gate whose result is never ambiguous
about which part of a chain produced it, and for never treating a
config string as code.

The rejected alternative -- `shell=True` once `verify_command_problem`
approves the string -- was not rejected on complexity grounds; it is the
simpler implementation. It loses because a validator with a shell
fallback only needs to be *good*, and this repository's own recent
history (the review that found `pytest 2>&1` and friends) is evidence
that "good" is not the same bar as "cannot fail unsafely." `shlex.split`
with no shell fails unsafely in the opposite, acceptable direction: a
gap in the detector produces a wrong argv and a confusing but bounded
error, never a string silently handed to `/bin/sh`.
