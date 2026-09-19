# SPDX-License-Identifier: BSD-3-Clause
"""Tests for plugins/antigravity manifests and configuration files."""

from __future__ import annotations

import json
import py_compile
import unittest

from tests.antigravity.conftest import AGY_PLUGIN_DIR


class PluginManifestTests(unittest.TestCase):
    def test_plugin_json_valid_and_named_canon(self) -> None:
        manifest_path = AGY_PLUGIN_DIR / "plugin.json"
        self.assertTrue(manifest_path.is_file(), f"{manifest_path} must exist")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("name"), "canon")
        self.assertEqual(data.get("version"), "0.1.0")


class McpConfigTests(unittest.TestCase):
    def test_mcp_config_json_valid(self) -> None:
        config_path = AGY_PLUGIN_DIR / "mcp_config.json"
        self.assertTrue(config_path.is_file(), f"{config_path} must exist")
        data = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        servers = data.get("mcpServers")
        self.assertIsInstance(servers, dict)
        canon_server = servers.get("canon")
        self.assertIsInstance(canon_server, dict)
        self.assertEqual(canon_server.get("command"), "uvx")
        args = canon_server.get("args")
        self.assertIsInstance(args, list)
        self.assertIn("canon-mcp", args)
        self.assertIn("vendor/canon_mcp", args)
        self.assertNotIn("../../src/canon_mcp", args)


class VendoredMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vendor_dir = AGY_PLUGIN_DIR / "vendor" / "canon_mcp"
        self.src_mcp_dir = AGY_PLUGIN_DIR.parent.parent / "src" / "canon_mcp"

    def test_vendored_mcp_exists_and_layout(self) -> None:
        self.assertTrue(self.vendor_dir.is_dir(), f"{self.vendor_dir} must exist")
        pyproject_path = self.vendor_dir / "pyproject.toml"
        self.assertTrue(pyproject_path.is_file(), f"{pyproject_path} must exist")
        pyproject_content = pyproject_path.read_text(encoding="utf-8")
        self.assertIn('name = "canon-mcp"', pyproject_content)
        self.assertIn('version = "0.1.0"', pyproject_content)

        # Ensure BUILD.bazel is not present in vendored directory
        self.assertFalse((self.vendor_dir / "BUILD.bazel").exists())

        # Check canon_mcp package directory
        pkg_dir = self.vendor_dir / "canon_mcp"
        self.assertTrue(pkg_dir.is_dir(), f"{pkg_dir} must exist")
        self.assertFalse((pkg_dir / "__pycache__").exists())

        expected_modules = {
            "__init__.py",
            "_config.py",
            "_decisions.py",
            "_gh.py",
            "_git.py",
            "_notebook.py",
            "_plan.py",
            "_steps.py",
            "evidence.py",
            "plan.py",
            "position.py",
            "review.py",
            "server.py",
            "ship.py",
        }
        vendored_files = {p.name for p in pkg_dir.glob("*.py")}
        self.assertEqual(vendored_files, expected_modules)

    def test_vendored_modules_match_source(self) -> None:
        pkg_dir = self.vendor_dir / "canon_mcp"
        src_pkg_dir = self.src_mcp_dir / "canon_mcp"
        if src_pkg_dir.is_dir():
            for py_file in pkg_dir.glob("*.py"):
                src_file = src_pkg_dir / py_file.name
                self.assertTrue(
                    src_file.is_file(),
                    f"{src_file} must exist in src/canon_mcp",
                )
                self.assertEqual(
                    py_file.read_text(encoding="utf-8"),
                    src_file.read_text(encoding="utf-8"),
                    f"{py_file.name} does not match source copy",
                )


class HooksManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hooks_path = AGY_PLUGIN_DIR / "hooks.json"
        self.assertTrue(self.hooks_path.is_file(), f"{self.hooks_path} must exist")
        self.data = json.loads(self.hooks_path.read_text(encoding="utf-8"))

    def test_hooks_json_structure(self) -> None:
        self.assertIsInstance(self.data, dict)
        expected_hooks = {
            "canon-plan-gate",
            "canon-git-guard",
            "canon-save-plan",
            "canon-check-scope",
            "canon-fast-check",
            "canon-session-context",
            "canon-stop",
        }
        self.assertEqual(set(self.data.keys()), expected_hooks)

    def test_lifecycle_events_and_matchers(self) -> None:
        # PreToolUse hooks
        plan_gate = self.data["canon-plan-gate"]["PreToolUse"][0]
        self.assertEqual(
            plan_gate["matcher"],
            "replace_file_content|write_to_file|run_command",
        )
        self.assertIn("hooks/plan_gate.py", plan_gate["hooks"][0]["command"])

        git_guard = self.data["canon-git-guard"]["PreToolUse"][0]
        self.assertEqual(git_guard["matcher"], "run_command")
        self.assertIn("hooks/git_guard.py", git_guard["hooks"][0]["command"])

        # PostToolUse hooks
        save_plan = self.data["canon-save-plan"]["PostToolUse"][0]
        self.assertEqual(save_plan["matcher"], "write_to_file")
        self.assertIn("hooks/save_plan.py", save_plan["hooks"][0]["command"])

        check_scope = self.data["canon-check-scope"]["PostToolUse"][0]
        self.assertEqual(check_scope["matcher"], "replace_file_content|write_to_file")
        self.assertIn("hooks/check_scope.py", check_scope["hooks"][0]["command"])

        fast_check = self.data["canon-fast-check"]["PostToolUse"][0]
        self.assertEqual(fast_check["matcher"], "replace_file_content|write_to_file")
        self.assertIn("hooks/fast_check.py", fast_check["hooks"][0]["command"])

        # PreInvocation hook
        session_ctx = self.data["canon-session-context"]["PreInvocation"][0]
        self.assertIn("hooks/session_context.py", session_ctx["command"])

        # Stop hook
        stop_hook = self.data["canon-stop"]["Stop"][0]
        self.assertIn("hooks/stop.py", stop_hook["command"])
        self.assertEqual(stop_hook.get("timeout"), 300)

    def test_hook_target_files_exist_and_compile(self) -> None:
        for hook_name, events in self.data.items():
            for _event_name, configs in events.items():
                for config in configs:
                    hook_entries = config.get("hooks", [config])
                    for entry in hook_entries:
                        command = entry.get("command", "")
                        # Command format: python3 hooks/<name>.py
                        script_name = command.split()[-1]
                        script_path = AGY_PLUGIN_DIR / script_name
                        self.assertTrue(
                            script_path.is_file(),
                            f"Hook {script_path} for {hook_name} must exist on disk",
                        )
                        # Verify python compilation passes
                        py_compile.compile(str(script_path), doraise=True)


class AgentsRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agents_md = AGY_PLUGIN_DIR / "rules" / "AGENTS.md"
        self.assertTrue(self.agents_md.is_file(), f"{self.agents_md} must exist")
        self.content = self.agents_md.read_text(encoding="utf-8")

    def test_core_invariants_documented(self) -> None:
        self.assertIn("Position is derived", self.content)
        self.assertIn("never stored", self.content)
        self.assertIn("Every gate fails open", self.content)
        self.assertIn("never authors a commit of its own", self.content)
        self.assertIn("never in the repository", self.content)
        self.assertIn("artifactDirectoryPath / conversationId / canon", self.content)

    def test_authorship_and_attribution_rules(self) -> None:
        self.assertIn("No `Co-Authored-By:` trailer", self.content)
        self.assertIn("Attribute the work to them and to no one else", self.content)


if __name__ == "__main__":
    unittest.main()
