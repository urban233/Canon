# SPDX-License-Identifier: BSD-3-Clause
"""Drive a real `canon-mcp` over stdio and check both `roots` arms.

`canon-mcp` resolves the repository it answers about. On Antigravity
that cannot come from the environment -- no workspace variable is
substituted into an `mcp_config.json`, and the server is spawned in the
*plugin* directory -- so it asks the client, via the protocol's own
`roots/list`. See
docs/decisions/0007-how-canon-mcp-learns-its-workspace-on-antigravity.md.

That resolver has two behaviours, and only one of them is about
Antigravity:

A. A client that declares `roots` is asked, and its answer must win over
   `CLAUDE_PROJECT_DIR`, `git rev-parse` and the process cwd.
B. A client that declares **no** `roots` capability must still get an
   answer. The SDK *raises* `MISSING_REQUIRED_CLIENT_CAPABILITY` when a
   resolver asks such a client, which would turn all five of Canon's
   tools into errors on Claude Code, where they work today. Arm B is the
   regression test for the platform this change could break.

Not a Bazel test: it needs `uvx` to resolve and launch the real server,
which the hermetic test toolchain deliberately has no access to -- the
same reason `server.py` is excluded from typecheck. The parsing and
policy half is covered hermetically in
`tests/test_canon_mcp_git.py::AdoptRootsTests`; this covers the wire.

Usage:

    python3 tools/check_mcp_roots.py src/canon_mcp

`_PROTOCOL` pins 2025-06-18 on purpose: from revision 2026-07-28 the
server batches its client-bound requests into an `InputRequiredResult`
that the client answers by retrying, rather than sending a standalone
`roots/list` mid-call. This harness speaks the simpler, older shape.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_PROTOCOL = "2025-06-18"
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Canon Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.com",
    "GIT_COMMITTER_NAME": "Canon Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.com",
}


def _git(directory: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )


def _make_repo(branch: str) -> Path:
    """A throwaway repository on `branch`, with Canon configured."""
    directory = Path(tempfile.mkdtemp(prefix="canon-mcp-e2e-"))
    _git(directory, "init", "-q")
    _git(directory, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(directory, "commit", "--allow-empty", "-q", "-m", "init")
    _git(directory, "checkout", "-q", "-b", branch)
    (directory / ".canon").mkdir()
    (directory / ".canon/config.json").write_text('{"verify": "true"}\n')
    _git(directory, "add", "-A")
    _git(directory, "commit", "-q", "-m", "config")
    return directory


class Client:
    """A minimal MCP client, just enough to call one tool."""

    def __init__(self, server_dir: Path, roots: list[dict[str, str]]) -> None:
        self.roots = roots
        self.asked_for_roots = False
        # A cwd that is deliberately *not* a repository, so a fallback to
        # `git rev-parse` cannot accidentally produce the right answer
        # and let arm A pass for the wrong reason.
        self.process = subprocess.Popen(
            ["uvx", "--from", str(server_dir), "canon-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=tempfile.mkdtemp(prefix="canon-mcp-cwd-"),
        )
        self._next_id = 100

    def _send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _receive(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            assert self.process.stderr is not None
            raise RuntimeError(f"server closed: {self.process.stderr.read()[-2000:]}")
        parsed: dict[str, Any] = json.loads(line)
        return parsed

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send one request and return its response.

        Server-to-client requests arriving while we wait are answered
        inline -- that is the whole point of the exercise for
        `roots/list`, and anything else gets an empty result so the
        server is never left blocking on us.
        """
        self._next_id += 1
        request_id = self._next_id
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        while True:
            message = self._receive()
            if message.get("method") == "roots/list":
                self.asked_for_roots = True
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"roots": self.roots},
                    }
                )
                continue
            if message.get("method") is not None and "id" in message:
                self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                continue
            if message.get("id") == request_id:
                return message

    def initialize(self, capabilities: dict[str, Any]) -> dict[str, Any]:
        response = self.request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL,
                "capabilities": capabilities,
                "clientInfo": {"name": "canon-roots-check", "version": "0"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response

    def close(self) -> None:
        try:
            assert self.process.stdin is not None
            self.process.stdin.close()
            self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()


def _reported_branch(result: dict[str, Any]) -> str | None:
    """The branch `canon_position` reported, from either output shape."""
    structured = result.get("structuredContent") or {}
    if not structured:
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    structured = json.loads(item["text"])
                except ValueError:
                    continue
    branch = structured.get("branch")
    return branch if isinstance(branch, str) else None


def _arm(
    name: str,
    capabilities: dict[str, Any],
    roots: list[dict[str, str]],
    server_dir: Path,
    expect_branch: str | None,
) -> bool:
    print(f"\n=== {name} ===")
    client = Client(server_dir, roots)
    try:
        initialized = client.initialize(capabilities)
        if "error" in initialized:
            print(f"  FAIL  initialize: {initialized['error']}")
            return False
        response = client.request(
            "tools/call", {"name": "canon_position", "arguments": {}}
        )
        if "error" in response:
            detail = json.dumps(response["error"])[:300]
            print(f"  FAIL  tools/call returned an error: {detail}")
            return False
        branch = _reported_branch(response.get("result", {}))
        if expect_branch is None:
            # The assertion is that the guarded resolver neither asked a
            # client that cannot answer nor raised
            # MISSING_REQUIRED_CLIENT_CAPABILITY. Whatever the fallback
            # lands on is not this arm's business.
            if client.asked_for_roots:
                print("  FAIL  asked a client that never declared the capability")
                return False
            print(f"  PASS  not asked, no error; fell back to branch {branch!r}")
            return True
        if branch != expect_branch:
            print(f"  FAIL  reported branch {branch!r}, wanted {expect_branch!r}")
            return False
        print(f"  PASS  adopted the client's root; branch {branch!r}")
        return True
    finally:
        client.close()


def main(argv: list[str]) -> int:
    server_dir = Path(argv[0] if argv else "src/canon_mcp").resolve()
    if shutil.which("uvx") is None:
        print(
            "uvx is not on PATH; this check needs it to launch the server",
            file=sys.stderr,
        )
        return 2

    repo = _make_repo("feature/from-roots")
    try:
        results = [
            _arm(
                "A: a client that declares roots is asked, and its answer wins",
                {"roots": {"listChanged": True}},
                [{"uri": repo.as_uri(), "name": "workspace"}],
                server_dir,
                "feature/from-roots",
            ),
            _arm(
                "B: a client that declares none is not asked, and does not error",
                {},
                [],
                server_dir,
                None,
            ),
        ]
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    passed = sum(1 for result in results if result)
    print(f"\n{passed}/{len(results)} arms as expected")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
