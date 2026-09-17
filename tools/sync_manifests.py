# SPDX-License-Identifier: BSD-3-Clause
"""Generates canon-companion's Codex plugin.json from its Claude one.

canon-companion is a skills-only plugin with nothing platform-specific in
it -- no hook, no MCP server, no bundled subagent -- so its Codex manifest
is generated from its Claude one plus the one key every OpenAI-shipped
skills plugin on this machine declares (`skills`) instead of being
hand-maintained a second time. A real `codex plugin add` confirmed this
key is not actually required for skill discovery at the default
`./skills/` path -- see docs/codex-hook-surface.md Part 5 -- so this is a
convention match, not a functional requirement.

Both `just sync-manifests` (writes the real, checked-in file) and
`just sync-check` (writes to a throwaway path and diffs against the
checked-in one) call this same script rather than each carrying their own
copy of the generation logic -- two copies of a generator can drift from
each other exactly like two copies of the generated file can, which would
leave `sync-check` red in a way `sync-manifests` itself could never clear.
"""

import json
import sys
from pathlib import Path

_CLAUDE_MANIFEST = Path("plugins/canon-companion/.claude-plugin/plugin.json")
_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"


def generate() -> dict[str, object]:
    data = json.loads(_CLAUDE_MANIFEST.read_text())
    generated: dict[str, object] = {"$schema": _SCHEMA}
    generated.update(data)
    generated["skills"] = "./skills/"
    return generated


def main() -> None:
    dest = Path(sys.argv[1])
    dest.write_text(json.dumps(generate(), indent=2) + "\n")


if __name__ == "__main__":
    main()
