# SPDX-License-Identifier: BSD-3-Clause
"""canon-mcp: the MCP server Canon ships with the plugin.

Three tools: `canon_position` (where the work stands), `canon_plan` (the
saved plan for this branch), and `canon_review` (which reviewers a diff
calls for, and the last captured verdict). `canon_evidence` and
`canon_ship`, also named in docs/plan.md §08, are Phase 1's remaining
tool and Phase 2's respectively -- not implemented here.

The only file in this package that imports `mcp`: confirmed directly
against a real install that the SDK is now v2 (`mcp.server.mcpserver
.MCPServer`, not the v1 `mcp.server.fastmcp.FastMCP`), and that
structured JSON output requires both a concrete return annotation
(`dict[str, Any]`, not bare `dict`) and `structured_output=True` on the
`@tool` decorator.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from ._git import repo_root
from .plan import build_plan
from .position import build_position
from .review import build_review

server = MCPServer("canon")


@server.tool(structured_output=True)
def canon_position() -> dict[str, Any]:
    """Where the work stands and the single next step."""
    return build_position(repo_root())


@server.tool(structured_output=True)
def canon_plan() -> dict[str, Any]:
    """The saved plan for this branch, and its parent feature plan if any."""
    return build_plan(repo_root())


@server.tool(structured_output=True)
def canon_review() -> dict[str, Any]:
    """Which reviewers this diff calls for, and the last verdict against
    this HEAD."""
    return build_review(repo_root())


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
