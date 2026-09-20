# SPDX-License-Identifier: BSD-3-Clause
"""Fail if the Antigravity plugin's manifests are not what Antigravity reads.

`agy plugin validate` does this job better, because it is the real
loader. It is also an IDE-bundled binary with no install path on a CI
runner -- wiring it into `just validate-plugin` turned `just ci` red
with `sh: 1: agy: not found`. So this is the portable floor under it:
stdlib only, runs anywhere, and checks the properties that actually
broke during the port rather than re-deriving a schema.

Deliberately *not* a general JSON-schema validator. Every rule below
exists because getting it wrong produces a plugin that loads cleanly and
then does nothing, which is the failure mode this whole port kept hitting
and the one no loader reports:

- A hook bound to `PreInvocation` runs and is ignored -- the language
  server calls it "deprecated and has no effect". A first draft of this
  port put Canon's session-context hook there.
- A hook command naming a file that is not in the plugin fails per
  invocation, silently, forever.
- An MCP `args` path that does not start with `${PLUGIN_ROOT}` resolves
  against a working directory the server does not have. `${WORKSPACE_ROOT}`
  is *not* substituted and reads as a literal.
- A skill or agent whose frontmatter lacks `description` is never
  selected, because the description is what the model matches on.

See docs/antigravity-hook-surface.md for how each was established.
Exit status is 0 when the plugin is sound, 1 otherwise, with every
problem named. Run it from the repository root.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_PLUGIN_DIR = Path("plugins/antigravity")

# The five events Antigravity documents. `PreInvocation` is listed as
# known-but-rejected rather than omitted: a typo should say "unknown
# event", and a binding there should say "this does nothing", because
# those are different mistakes with different fixes.
_GROUPED_EVENTS = frozenset({"PreToolUse", "PostToolUse"})
_FLAT_EVENTS = frozenset({"PostInvocation", "Stop"})
_DEAD_EVENTS = {
    "PreInvocation": (
        "runs but its output is ignored -- the language server reports it as "
        "'deprecated and has no effect'. Use PostInvocation, gated on "
        "invocationNum, for anything that needs to inject."
    )
}
_KNOWN_EVENTS = _GROUPED_EVENTS | _FLAT_EVENTS | frozenset(_DEAD_EVENTS)

# `python3 hooks/stop.py`, possibly with flags. The interpreter is not
# policed -- only that whatever .py file is named actually ships.
_SCRIPT_IN_COMMAND = re.compile(r"(?:^|\s)((?:[\w./-]+/)?[\w.-]+\.py)(?:\s|$)")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_FRONTMATTER_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:", re.MULTILINE)

_PLUGIN_ROOT_PREFIX = "${PLUGIN_ROOT}/"
# Everything else a reader might reasonably expect to be substituted, and
# which is not. Confirmed by capture: only ${PLUGIN_ROOT} and
# ${PLUGIN_DATA} expand in an mcp_config.json.
_UNSUBSTITUTED = ("${WORKSPACE_ROOT}", "${CONVERSATION_ID}", "${CLAUDE_PLUGIN_ROOT}")


def _load_json(path: Path, problems: list[str]) -> dict[str, Any] | None:
    """Parse `path` as a JSON object, recording a problem on failure."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        problems.append(f"{path}: cannot be read ({error})")
        return None
    except ValueError as error:
        problems.append(f"{path}: is not valid JSON ({error})")
        return None
    if not isinstance(data, dict):
        problems.append(f"{path}: top level must be a JSON object")
        return None
    return data


def _check_handler(handler: Any, where: str, root: Path, problems: list[str]) -> None:
    """One `{type, command, timeout}` entry."""
    if not isinstance(handler, dict):
        problems.append(f"{where}: each handler must be an object")
        return
    kind = handler.get("type", "command")
    if kind != "command":
        problems.append(f"{where}: type {kind!r} is not supported -- only 'command' is")
    command = handler.get("command")
    if not isinstance(command, str) or not command.strip():
        problems.append(f"{where}: needs a non-empty 'command'")
        return
    timeout = handler.get("timeout")
    if timeout is not None and not isinstance(timeout, int):
        problems.append(f"{where}: 'timeout' must be a whole number of seconds")
    # A hook runs with its working directory set to the directory holding
    # hooks.json, so a relative script path is relative to the plugin root.
    match = _SCRIPT_IN_COMMAND.search(command)
    if match is None:
        return
    script = match.group(1)
    if script.startswith("/"):
        problems.append(
            f"{where}: command names an absolute path ({script}); it will not "
            f"exist on a machine that installed the plugin elsewhere"
        )
        return
    if not (root / script).is_file():
        problems.append(f"{where}: command names {script}, which is not in the plugin")


def _check_hooks(root: Path, problems: list[str]) -> None:
    path = root / "hooks.json"
    if not path.is_file():
        return  # hooks are optional; a plugin may ship only skills
    data = _load_json(path, problems)
    if data is None:
        return
    for name, spec in data.items():
        if not isinstance(spec, dict):
            problems.append(f"hooks.json [{name}]: must be an object")
            continue
        events = [key for key in spec if key != "enabled"]
        if not events:
            problems.append(f"hooks.json [{name}]: declares no event")
        for event in events:
            where = f"hooks.json [{name}].{event}"
            if event in _DEAD_EVENTS:
                problems.append(f"{where}: {_DEAD_EVENTS[event]}")
                continue
            if event not in _KNOWN_EVENTS:
                problems.append(
                    f"{where}: unknown event -- expected one of "
                    f"{', '.join(sorted(_KNOWN_EVENTS))}"
                )
                continue
            entries = spec[event]
            if not isinstance(entries, list) or not entries:
                problems.append(f"{where}: must be a non-empty array")
                continue
            if event in _GROUPED_EVENTS:
                for index, group in enumerate(entries):
                    slot = f"{where}[{index}]"
                    if not isinstance(group, dict):
                        problems.append(f"{slot}: must be an object")
                        continue
                    if "matcher" not in group:
                        problems.append(
                            f"{slot}: a tool event needs a 'matcher' -- without "
                            f"one this group matches nothing"
                        )
                    inner = group.get("hooks")
                    if not isinstance(inner, list) or not inner:
                        problems.append(
                            f"{slot}: a tool event wraps its handlers in a "
                            f"non-empty 'hooks' array"
                        )
                        continue
                    for position, handler in enumerate(inner):
                        _check_handler(
                            handler, f"{slot}.hooks[{position}]", root, problems
                        )
            else:
                for index, handler in enumerate(entries):
                    if isinstance(handler, dict) and "hooks" in handler:
                        problems.append(
                            f"{where}[{index}]: {event} takes handler objects "
                            f"directly, not a 'matcher'/'hooks' wrapper"
                        )
                        continue
                    _check_handler(handler, f"{where}[{index}]", root, problems)


def _check_mcp(root: Path, problems: list[str]) -> None:
    path = root / "mcp_config.json"
    if not path.is_file():
        return
    data = _load_json(path, problems)
    if data is None:
        return
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        problems.append("mcp_config.json: needs a non-empty 'mcpServers' object")
        return
    for name, spec in servers.items():
        where = f"mcp_config.json [{name}]"
        if not isinstance(spec, dict):
            problems.append(f"{where}: must be an object")
            continue
        if "serverUrl" in spec:
            continue  # remote server: nothing local to resolve
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            problems.append(f"{where}: needs a 'command'")
        elif command.startswith("."):
            problems.append(
                f"{where}: a relative command ({command}) is not resolved -- "
                f"Antigravity looks it up on PATH"
            )
        values = list(spec.get("args") or []) + list((spec.get("env") or {}).values())
        for value in values:
            if not isinstance(value, str):
                continue
            for literal in _UNSUBSTITUTED:
                if literal in value:
                    problems.append(
                        f"{where}: {literal} is not substituted here and will "
                        f"reach the server as a literal string"
                    )
            if value.startswith(_PLUGIN_ROOT_PREFIX):
                relative = value[len(_PLUGIN_ROOT_PREFIX) :]
                if not (root / relative).exists():
                    problems.append(
                        f"{where}: {value} points at {relative}, which is not "
                        f"in the plugin"
                    )


def _check_frontmatter(path: Path, label: str, problems: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        problems.append(f"{path}: cannot be read ({error})")
        return
    # An agent brief may open with an HTML comment explaining the port;
    # frontmatter still has to be the first thing the loader sees, so
    # this looks for it at the very top and also after one comment block.
    body = text
    if body.startswith("<!--") and "-->" in body:
        body = body.split("-->", 1)[1].lstrip("\n")
    match = _FRONTMATTER.match(body)
    if match is None:
        problems.append(f"{path}: {label} needs a '---' frontmatter block")
        return
    keys = set(_FRONTMATTER_KEY.findall(match.group(1)))
    for required in ("name", "description"):
        if required not in keys:
            problems.append(
                f"{path}: {label} frontmatter needs '{required}' -- without a "
                f"description the model never selects it"
            )


def _check_skills_and_agents(root: Path, problems: list[str]) -> None:
    skills = root / "skills"
    if skills.is_dir():
        for directory in sorted(p for p in skills.iterdir() if p.is_dir()):
            manifest = directory / "SKILL.md"
            if not manifest.is_file():
                problems.append(f"{directory}: a skill needs a SKILL.md")
                continue
            _check_frontmatter(manifest, "a skill", problems)
    agents = root / "agents"
    if agents.is_dir():
        briefs = sorted(agents.glob("*.md")) + sorted(agents.glob("*/agent.md"))
        if not briefs:
            problems.append(
                f"{agents}: exists but holds no agent brief -- expected "
                f"<name>.md or <name>/agent.md"
            )
        for brief in briefs:
            _check_frontmatter(brief, "an agent", problems)


def check(root: Path) -> list[str]:
    """Every problem found in the plugin at `root`."""
    problems: list[str] = []
    if not root.is_dir():
        return [f"{root}: no such plugin directory"]
    manifest = root / "plugin.json"
    if not manifest.is_file():
        problems.append(f"{root}: a plugin needs a plugin.json")
    else:
        data = _load_json(manifest, problems)
        if data is not None and not isinstance(data.get("name"), str):
            problems.append(f"{manifest}: needs a string 'name'")
    _check_hooks(root, problems)
    _check_mcp(root, problems)
    _check_skills_and_agents(root, problems)
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else _PLUGIN_DIR
    problems = check(root)
    if problems:
        print(f"{root}: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"{root}: manifests, hooks, skills and agents check out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
