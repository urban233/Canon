# SPDX-License-Identifier: BSD-3-Clause
"""canon-mcp: the MCP server Canon ships with the plugin.

Two tools, per docs/plan.md §08's Phase 0 scope: `canon_position` (where
the work stands) and `canon_plan` (the saved plan for this branch). The
other three tools named in §08 -- `canon_evidence`, `canon_review`,
`canon_ship` -- are Phase 1/2 and not implemented here.

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

server = MCPServer("canon")


@server.tool(structured_output=True)
def canon_position() -> dict[str, Any]:
    """Where the work stands and the single next step."""
    return build_position(repo_root())


@server.tool(structured_output=True)
def canon_plan() -> dict[str, Any]:
    """The saved plan for this branch, and its parent feature plan if any."""
    return build_plan(repo_root())


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
