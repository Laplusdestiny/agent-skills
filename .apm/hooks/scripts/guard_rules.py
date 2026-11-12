"""Guardrail rule definitions and evaluation for the PreToolUse hook."""

from __future__ import annotations

from typing import NamedTuple, Optional


class Action(NamedTuple):
    kind: str  # "shell" | "write"
    value: str  # shell command or file path


class Decision(NamedTuple):
    decision: str  # "deny" | "ask" | "allow"
    rule_id: str
    reason: str


def evaluate(action: Action) -> Optional[Decision]:
    return None
