"""Tests for the guardrail hook entrypoint (.apm/hooks/scripts/guard.py)."""

import io
import json
import os
import shutil
import subprocess
import sys
import unittest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".apm", "hooks", "scripts"
)
GUARD = os.path.join(SCRIPTS_DIR, "guard.py")
sys.dont_write_bytecode = True  # keep the scripts dir clean for the bytecode test
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


def run_guard(payload):
    proc = subprocess.run(
        [sys.executable, GUARD], input=json.dumps(payload), capture_output=True, text=True, timeout=30
    )
    return proc.returncode, proc.stdout


class EndToEndTest(unittest.TestCase):
    def test_e2e_claude_deny(self):
        code, out = run_guard({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_e2e_claude_allow(self):
        code, out = run_guard({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git status"}})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_e2e_claude_write_ask(self):
        code, out = run_guard({"tool_name": "Edit", "tool_input": {"file_path": "/repo/.claude/settings.json"}})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_e2e_copilot_ask_is_deny(self):
        code, out = run_guard({"toolName": "bash", "toolArgs": json.dumps({"command": "git reset --hard"})})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["permissionDecision"], "deny")

    def test_e2e_unrelated_tool_is_silent(self):
        code, out = run_guard({"tool_name": "Read", "tool_input": {"file_path": "/repo/.env"}})
        self.assertEqual((code, out), (0, ""))

    def test_e2e_does_not_write_bytecode(self):
        shutil.rmtree(os.path.join(SCRIPTS_DIR, "__pycache__"), ignore_errors=True)
        run_guard({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertFalse(os.path.exists(os.path.join(SCRIPTS_DIR, "__pycache__")))


if __name__ == "__main__":
    unittest.main()
