# SPDX-License-Identifier: BSD-3-Clause
"""Run Canon's eval cases against the Antigravity plugin.

`claude plugin eval` is what runs the Claude suite, and there is no
Antigravity equivalent -- so the two cases under
`plugins/antigravity/evals/` were shape-checked but unrunnable, which
means the instruction text they guard was never actually exercised. This
is the runner that closes that, reading the *same* `case.yaml` /
`prompt.md` / `graders/*.md` layout rather than inventing a second
format: a case should be portable between platforms, because the
behaviour Canon asks for is supposed to be.

Not a reimplementation of the whole harness. It covers what these cases
need and refuses loudly on anything else, because a runner that quietly
skips a grader reports a pass the suite never earned -- the same failure
`tests/test_evals_graders.py` exists to prevent one step earlier.

## Cost

Every case is a real model turn on the developer's own Antigravity
account, and `--judge` adds one more per LLM grader. Nothing here runs
in CI: `docs/decisions/0003-eval-suite-is-not-a-ci-gate.md` bars wiring
a billed, model-backed run into `just ci`, and that reasoning is about
the cost of the run, not about which vendor bills it. Deterministic
graders (`regex`, `files`, `tool_used`) cost nothing beyond the turn
itself and run by default; `llm` graders are reported as UNJUDGED unless
`--judge` is passed.

## Permissions

`agy` in `--print` mode cannot prompt, so a tool needing permission is
auto-denied and the turn produces **no output at all**. Graded naively
that reads as an instruction failure, which is the most expensive
mistake this runner could make: it would send someone rewriting skill
text that was working. Grant the case's tools once in
`~/.gemini/antigravity-cli/settings.json`:

    {"permissions": {"allow": ["read_file(*)", "write_file(*)", "mcp(*)"]}}

`mcp(*)` matters as much as the file rules -- Canon's `review` and
`ship` skills open by calling a `canon_*` tool, so a case exercising
them is denied on `mcp` before it reads a single file.

Two guards, because one was not enough. `--check-permissions` (the
default) refuses to start without that file; and every case is checked
after the fact for the auto-deny signature, and reported CONFOUNDED
rather than graded if it is found.

Usage:

    python3 tools/eval_antigravity.py                     # every case
    python3 tools/eval_antigravity.py --case <name>       # one case
    python3 tools/eval_antigravity.py --judge             # grade llm too
    python3 tools/eval_antigravity.py --dry-run           # scaffold only
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

_SUITE = Path("plugins/antigravity/evals")
_SETTINGS = Path.home() / ".gemini/antigravity-cli/settings.json"
_AGY = Path.home() / ".gemini/bin/agy"
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

_DETERMINISTIC = frozenset({"regex", "files", "tool_used"})
_KNOWN_TYPES = _DETERMINISTIC | frozenset({"llm"})

# What `agy --print` says when it hits a permission it cannot prompt
# for. The turn produces no output, so a `not_contains` grader passes
# vacuously and an `llm` grader fails on an empty reply -- a result that
# looks like a verdict on the instructions and is nothing of the kind.
# docs/decisions/0003 makes this point about paid runs; the same applies
# to a run that was paid for and then wasted.
_AUTO_DENIED = "headless mode cannot prompt"


class Grader(NamedTuple):
    name: str
    fields: dict[str, str]
    body: str


class Outcome(NamedTuple):
    grader: str
    verdict: str  # PASS | FAIL | UNJUDGED
    detail: str


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a `---` block into scalar fields plus the remaining body.

    Deliberately not YAML: the graders use one `key: value` per line and
    nothing nested, and depending on a YAML library would put a third-party
    import in a path that has to run on whatever `python3` is present.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.split("#", 1)[0].rstrip() if line.lstrip().startswith("#") else line
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("'\"")
    return fields, match.group(2)


def _load_case(directory: Path) -> tuple[dict[str, str], str, list[Grader]]:
    prompt_fields, prompt_body = _parse_frontmatter(
        (directory / "prompt.md").read_text(encoding="utf-8")
    )
    graders: list[Grader] = []
    for path in sorted((directory / "graders").glob("*.md")):
        fields, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        graders.append(Grader(path.stem, fields, body.strip()))
    return prompt_fields, prompt_body.strip(), graders


def _scaffold(directory: Path, workspace: Path) -> None:
    fixture = directory / "fixture.sh"
    subprocess.run(
        ["bash", str(fixture.resolve())],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_case(workspace: Path, prompt: str, timeout: int) -> tuple[str, str]:
    """Run one turn; return (reply text, raw stdout+stderr as the trace)."""
    completed = subprocess.run(
        [
            str(_AGY),
            "-p",
            prompt,
            "--print-timeout",
            f"{timeout}s",
            "--output-format",
            "text",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=timeout + 60,
        check=False,
    )
    trace = (completed.stdout or "") + (completed.stderr or "")
    return (completed.stdout or "").strip(), trace


def _created_files(workspace: Path) -> str:
    """Newline-separated repo-relative paths, for `target: files`."""
    paths: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and ".git" not in path.parts:
            paths.append(str(path.relative_to(workspace)))
    return "\n".join(paths)


def _target_text(grader: Grader, workspace: Path, reply: str, trace: str) -> str | None:
    target = grader.fields.get("target", "trace")
    if target == "files":
        return _created_files(workspace)
    if target == "trace":
        return trace + "\n" + reply
    match = re.match(r"\{\s*source:\s*file\s*,\s*path:\s*(?P<path>[^}]+?)\s*\}", target)
    if match is None:
        return None
    path = workspace / match.group("path").strip()
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _grade_regex(grader: Grader, text: str) -> Outcome:
    pattern = grader.fields.get("pattern")
    if pattern is None:
        return Outcome(grader.name, "FAIL", "grader declares no pattern")
    flags = 0
    for flag in grader.fields.get("flags", ""):
        flags |= {"m": re.MULTILINE, "s": re.DOTALL, "i": re.IGNORECASE}.get(flag, 0)
    found = re.search(pattern, text, flags) is not None
    mode = grader.fields.get("match", "contains")
    if mode not in ("contains", "not_contains"):
        return Outcome(grader.name, "FAIL", f"unknown match mode {mode!r}")
    ok = found if mode == "contains" else not found
    return Outcome(
        grader.name,
        "PASS" if ok else "FAIL",
        f"{'found' if found else 'no match'} for /{pattern}/ (match: {mode})",
    )


def _grade_tool_used(grader: Grader, trace: str) -> Outcome:
    needle = grader.fields.get("input_match") or grader.fields.get("tool", "")
    count = trace.count(needle) if needle else 0
    low = int(grader.fields.get("min", 0))
    high = int(grader.fields.get("max", 10**6))
    ok = low <= count <= high
    return Outcome(
        grader.name,
        "PASS" if ok else "FAIL",
        f"saw {needle!r} {count} time(s); wanted {low}..{high}",
    )


def _judge(grader: Grader, reply: str, workspace: Path) -> Outcome:
    """Ask a fresh Antigravity turn to apply one LLM grader."""
    question = (
        "You are grading one transcript against one criterion. Answer with "
        "exactly PASS or FAIL on the first line, then one sentence of "
        "reasoning.\n\n=== CRITERION ===\n"
        + grader.body
        + "\n\n=== REPLY UNDER TEST ===\n"
        + reply
    )
    with tempfile.TemporaryDirectory() as scratch:
        completed = subprocess.run(
            [str(_AGY), "-p", question, "--print-timeout", "120s"],
            cwd=scratch,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    answer = (completed.stdout or "").strip()
    verdict = "PASS" if answer.upper().lstrip().startswith("PASS") else "FAIL"
    return Outcome(grader.name, verdict, answer.splitlines()[0][:160] if answer else "")


def run_case(directory: Path, *, judge: bool, dry_run: bool) -> list[Outcome]:
    prompt_fields, prompt, graders = _load_case(directory)
    timeout = int(prompt_fields.get("timeout_seconds", "240"))
    workspace = Path(tempfile.mkdtemp(prefix=f"canon-eval-{directory.name}-"))
    try:
        _scaffold(directory, workspace)
        if dry_run:
            return [Outcome("(dry-run)", "UNJUDGED", f"scaffolded at {workspace}")]
        reply, trace = _run_case(workspace, prompt, timeout)
        if _AUTO_DENIED in trace:
            tool = re.search(r'required the "([^"]+)" permission', trace)
            missing = tool.group(1) if tool else "a tool"
            return [
                Outcome(
                    "(not run)",
                    "CONFOUNDED",
                    f"auto-denied on the {missing!r} permission -- this says "
                    f"nothing about the instructions; grant it and re-run",
                )
            ]
        outcomes: list[Outcome] = []
        for grader in graders:
            kind = grader.fields.get("type", "")
            if kind not in _KNOWN_TYPES:
                outcomes.append(
                    Outcome(grader.name, "FAIL", f"unsupported grader type {kind!r}")
                )
            elif kind == "llm":
                outcomes.append(
                    _judge(grader, reply, workspace)
                    if judge
                    else Outcome(grader.name, "UNJUDGED", "pass --judge to grade")
                )
            elif kind == "tool_used":
                outcomes.append(_grade_tool_used(grader, trace))
            else:
                text = _target_text(grader, workspace, reply, trace)
                if text is None:
                    outcomes.append(Outcome(grader.name, "FAIL", "unreadable target"))
                else:
                    outcomes.append(_grade_regex(grader, text))
        return outcomes
    finally:
        if not dry_run:
            shutil.rmtree(workspace, ignore_errors=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="run only this case directory name")
    parser.add_argument("--judge", action="store_true", help="grade llm graders too")
    parser.add_argument("--dry-run", action="store_true", help="scaffold only")
    parser.add_argument(
        "--check-permissions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="refuse to run without an allow-rule file",
    )
    args = parser.parse_args(argv)

    if not _AGY.exists():
        print(f"{_AGY}: not found -- is Antigravity installed?", file=sys.stderr)
        return 2
    if not args.dry_run and args.check_permissions and not _SETTINGS.exists():
        print(
            f"{_SETTINGS} does not exist. `agy --print` cannot prompt for tool "
            f"permission, so every case would fail for a reason that says "
            f"nothing about the instructions. Create it with the allow-rules "
            f"the cases need (see this file's docstring), or pass "
            f"--no-check-permissions to run anyway.",
            file=sys.stderr,
        )
        return 2

    cases = sorted(p for p in _SUITE.iterdir() if (p / "case.yaml").is_file())
    if args.case:
        cases = [p for p in cases if p.name == args.case]
        if not cases:
            print(f"no such case: {args.case}", file=sys.stderr)
            return 2

    failed = 0
    confounded = 0
    for directory in cases:
        print(f"\n=== {directory.name} ===")
        try:
            outcomes = run_case(directory, judge=args.judge, dry_run=args.dry_run)
        except (subprocess.SubprocessError, OSError) as error:
            print(f"  ERROR      could not run: {error}")
            failed += 1
            continue
        for outcome in outcomes:
            print(f"  {outcome.verdict:<10} {outcome.grader}: {outcome.detail}")
        if any(outcome.verdict == "CONFOUNDED" for outcome in outcomes):
            confounded += 1
        elif any(outcome.verdict == "FAIL" for outcome in outcomes):
            failed += 1

    clean = len(cases) - failed - confounded
    print(f"\n{clean}/{len(cases)} case(s) clean")
    if confounded:
        print(
            f"{confounded} case(s) could not be run and were NOT graded. "
            f"Nothing here is evidence about the instructions until they are."
        )
    return 1 if (failed or confounded) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
