#!/usr/bin/env python3
"""PreToolUse guardrail hook for Claude Code and GitHub Copilot.

Reads the hook payload from stdin, normalizes it into an Action, evaluates it
against guard_rules, and prints a decision in the calling harness's format.
Prints nothing when no rule applies. Fails open (exit 0) on unexpected errors.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional, TextIO, Tuple

sys.dont_write_bytecode = True  # keep deployed hook dirs free of __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard_rules import Action, Decision, evaluate  # noqa: E402

WRITE_TOOL_HINTS = ("edit", "write", "create", "replace", "insert")
# Claude: Read / Grep, Copilot CLI: view / grep, VS Code: read_file
READ_TOOLS = {"read", "grep", "view", "read_file"}
PATH_KEYS = ("file_path", "path", "filePath", "notebook_path")


def _path_arg(args: Dict[str, Any]) -> Optional[str]:
    for key in PATH_KEYS:
        path = args.get(key)
        if isinstance(path, str) and path:
            return path
    return None


def _to_action(tool_name: str, args: Dict[str, Any]) -> Optional[Action]:
    command = args.get("command")
    if isinstance(command, str):
        return Action("shell", command)
    lowered = tool_name.lower()
    path = _path_arg(args)
    if path is None:
        return None
    if any(hint in lowered for hint in WRITE_TOOL_HINTS):
        return Action("write", path)
    if lowered in READ_TOOLS:
        return Action("read", path)
    return None


def parse_input(payload: Dict[str, Any]) -> Tuple[Optional[Action], str]:
    """Return (action, harness). harness is "claude" or "copilot"."""
    if "toolName" in payload:
        raw = payload.get("toolArgs")
        if isinstance(raw, str):
            try:
                args = json.loads(raw) if raw else {}
            except ValueError:
                args = {}
        else:
            args = raw if isinstance(raw, dict) else {}
        if not isinstance(args, dict):
            args = {}
        return _to_action(str(payload.get("toolName") or ""), args), "copilot"
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    return _to_action(str(payload.get("tool_name") or ""), tool_input), "claude"


def format_output(decision: Optional[Decision], harness: str) -> Optional[Dict[str, Any]]:
    if decision is None:
        return None
    reason = "[guardrails {}] {}".format(decision.rule_id, decision.reason)
    if harness == "copilot":
        if decision.decision == "allow":
            return None
        if decision.decision == "ask":
            reason += " (requires user confirmation; ask the user to run it manually)"
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision.decision,
            "permissionDecisionReason": reason,
        }
    }


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    try:
        payload = json.loads(stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        action, harness = parse_input(payload)
        if action is None:
            return 0
        output = format_output(evaluate(action), harness)
        if output is not None:
            stdout.write(json.dumps(output, ensure_ascii=False))
        return 0
    except Exception as exc:  # fail open: a guard bug must not block every tool
        sys.stderr.write("[guardrails] hook error (ignored): {}\n".format(exc))
        return 0


if __name__ == "__main__":
    sys.exit(main())
