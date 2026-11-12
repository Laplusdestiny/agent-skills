"""Tests for the guardrail hook entrypoint (.apm/hooks/scripts/guard.py)."""

import io
import json
import os
import sys
import unittest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".apm", "hooks", "scripts"
)
GUARD = os.path.join(SCRIPTS_DIR, "guard.py")
sys.path.insert(0, SCRIPTS_DIR)

import guard  # noqa: E402
from guard_rules import Action, Decision  # noqa: E402


class ParseInputTest(unittest.TestCase):
    def test_parse_claude_bash(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.assertEqual(guard.parse_input(payload), (Action("shell", "ls"), "claude"))

    def test_parse_claude_write(self):
        for tool in ("Write", "Edit", "MultiEdit"):
            payload = {"tool_name": tool, "tool_input": {"file_path": "/repo/a.py"}}
            self.assertEqual(guard.parse_input(payload), (Action("write", "/repo/a.py"), "claude"), tool)
        payload = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/repo/n.ipynb"}}
        self.assertEqual(guard.parse_input(payload), (Action("write", "/repo/n.ipynb"), "claude"))

    def test_parse_copilot_bash(self):
        payload = {"toolName": "bash", "toolArgs": json.dumps({"command": "ls"})}
        self.assertEqual(guard.parse_input(payload), (Action("shell", "ls"), "copilot"))

    def test_parse_copilot_edit(self):
        for tool in ("edit", "create"):
            payload = {"toolName": tool, "toolArgs": json.dumps({"path": "/repo/.env"})}
            self.assertEqual(guard.parse_input(payload), (Action("write", "/repo/.env"), "copilot"), tool)

    def test_parse_other_tool(self):
        for tool in ("Read", "Grep"):
            payload = {"tool_name": tool, "tool_input": {"file_path": "/repo/a.py", "pattern": "x"}}
            self.assertEqual(guard.parse_input(payload), (None, "claude"), tool)


class FormatOutputTest(unittest.TestCase):
    def test_format_claude(self):
        out = guard.format_output(Decision("deny", "D1", "no"), "claude")
        self.assertEqual(
            out,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "[guardrails D1] no",
                }
            },
        )

    def test_format_copilot_ask_becomes_deny(self):
        out = guard.format_output(Decision("ask", "A1", "destructive"), "copilot")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("[guardrails A1] destructive", out["permissionDecisionReason"])
        self.assertIn("manually", out["permissionDecisionReason"])

    def test_format_copilot_allow_is_silent(self):
        self.assertIsNone(guard.format_output(Decision("allow", "L1", "read-only"), "copilot"))

    def test_format_none_is_silent(self):
        self.assertIsNone(guard.format_output(None, "claude"))


class MainTest(unittest.TestCase):
    def test_main_invalid_json(self):
        stdout = io.StringIO()
        self.assertEqual(guard.main(io.StringIO("not json"), stdout), 0)
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
