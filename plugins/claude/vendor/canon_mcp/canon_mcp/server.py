# SPDX-License-Identifier: BSD-3-Clause
"""canon-mcp: the MCP server Canon ships with the plugin.

Five tools: `canon_position` (where the work stands), `canon_plan` (the
saved plan for this branch), `canon_review` (which reviewers a diff
calls for, and the last captured verdict), `canon_evidence` (whether
this commit is green, and where that was established), and `canon_ship`
(whether this is ready for a human, and precisely what's missing if
not).

The only file in this package that imports `mcp`: confirmed directly
against a real install that the SDK is now v2 (`mcp.server.mcpserver
.MCPServer`, not the v1 `mcp.server.fastmcp.FastMCP`), and that
structured JSON output requires both a concrete return annotation
(`dict[str, Any]`, not bare `dict`) and `structured_output=True` on the
`@tool` decorator.

Every tool takes a `workspace` parameter, which the LLM never supplies:
it is filled by the `_workspace_roots` resolver below, which asks the
client where it is working. See that function for why it is guarded, and
docs/decisions/0007-how-canon-mcp-learns-its-workspace-on-antigravity.md
for why asking is necessary at all on Antigravity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Context, ListRoots, MCPServer, Resolve
from mcp_types import ListRootsResult

from ._git import adopt_roots, repo_root
from .evidence import build_evidence
from .plan import build_plan
from .position import build_position
from .review import build_review
from .ship import build_ship

server = MCPServer("canon")


def _workspace_roots(ctx: Context) -> ListRootsResult | ListRoots:
    """Ask the client for its workspace roots -- but only if it can answer.

    The capability check is the whole point of this function existing
    rather than the tools simply declaring `ListRoots`. The SDK *raises*
    `MISSING_REQUIRED_CLIENT_CAPABILITY` when a resolver asks a client
    that never declared `roots`, which would turn every one of Canon's
    five tools into an error on any such host -- including Claude Code,
    where they work today. Degrading to an empty result instead means
    `repo_root()` falls through to the environment sources it has always
    used, and nothing changes for a client that does not offer roots.

    Antigravity's client declares `roots` with `listChanged: true`
    (confirmed directly against a live session). Note that `roots` is
    deprecated as of protocol revision 2026-07-28, so this is expected to
    need replacing; `_git.set_client_root` is the seam that keeps that a
    one-call-site change.
    """
    capabilities = ctx.client_capabilities
    if capabilities is not None and capabilities.roots is not None:
        return ListRoots()
    return ListRootsResult(roots=[])


Workspace = Annotated[ListRootsResult, Resolve(_workspace_roots)]


def _root(workspace: ListRootsResult) -> Path:
    """The repository to answer about, preferring what the client said.

    `adopt_roots` records the client's answer so that `repo_root()` --
    which the rest of the package calls with no arguments -- prefers it
    over `CLAUDE_PROJECT_DIR`, `git rev-parse` and the process cwd. An
    empty or unusable answer clears the record rather than leaving a
    stale one, so a client that stops offering a workspace does not make
    the server answer confidently about the wrong repository.
    """
    adopt_roots(str(root.uri) for root in workspace.roots)
    return repo_root()


@server.tool(structured_output=True)
def canon_position(workspace: Workspace) -> dict[str, Any]:
    """Where the work stands and the single next step."""
    return build_position(_root(workspace))


@server.tool(structured_output=True)
def canon_plan(workspace: Workspace) -> dict[str, Any]:
    """The saved plan for this branch, and its parent feature plan if any."""
    return build_plan(_root(workspace))


@server.tool(structured_output=True)
def canon_review(workspace: Workspace) -> dict[str, Any]:
    """Which reviewers this diff calls for, and the last verdict against
    this HEAD."""
    return build_review(_root(workspace))


@server.tool(structured_output=True)
def canon_evidence(workspace: Workspace) -> dict[str, Any]:
    """Whether this commit is green, and where that was established."""
    return build_evidence(_root(workspace))


@server.tool(structured_output=True)
def canon_ship(workspace: Workspace) -> dict[str, Any]:
    """Whether this is ready for a human, and precisely what's missing
    if not."""
    return build_ship(_root(workspace))


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
