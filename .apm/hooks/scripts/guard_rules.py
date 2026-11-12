"""Guardrail rule definitions and evaluation for the PreToolUse hook.

Decisions, strongest first: deny > ask > allow. ``evaluate`` returns None when
no rule applies, leaving the decision to the harness's normal permission flow.

To add a rule, write a small predicate and append a ``Rule`` to ``RULES``.
Scopes:
  - "segment":     predicate(tokens) on each command segment, with leading
                   wrappers such as ``sudo`` / ``env`` / ``nohup`` stripped
  - "raw_segment": predicate(tokens) on each segment as written
  - "command":     predicate(command) on the whole command string
  - "path":        predicate(path) on a file path being written, with "\\"
                   normalized to "/" and a leading "/" ensured
"""

from __future__ import annotations

import os
import re
import shlex
from typing import Callable, List, NamedTuple, Optional, Sequence, Tuple


class Action(NamedTuple):
    kind: str  # "shell" | "write"
    value: str  # shell command or file path


class Decision(NamedTuple):
    decision: str  # "deny" | "ask" | "allow"
    rule_id: str
    reason: str


class Rule(NamedTuple):
    id: str
    decision: str  # "deny" | "ask"
    scope: str  # "segment" | "raw_segment" | "command" | "path"
    check: Callable
    reason: str


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------

SEPARATORS = {"&&", "||", ";", "|", "&", "\n", ";;", "|&"}
PREFIX_COMMANDS = {"sudo", "doas", "env", "nohup", "time", "command", "exec", "nice"}
# options of prefix commands that consume the following token
PREFIX_VALUE_OPTIONS = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S"},
    "nice": {"-n"},
}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def split_segments(command: str) -> Tuple[List[List[str]], bool]:
    """Split a shell command into token lists, one per simple command.

    Returns (segments, ok). ``ok`` is False when shlex could not parse the
    command (e.g. unbalanced quotes) and a rough whitespace split was used.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
        ok = True
    except ValueError:
        tokens = [t for t in re.split(r"(&&|\|\||[;|&\n])|[ \t\r]+", command) if t]
        ok = False
    segments: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in SEPARATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments, ok


def strip_prefix(tokens: List[str]) -> List[str]:
    """Drop leading wrappers (sudo, env, nohup, ...) and VAR=value assignments."""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if ASSIGNMENT.match(token):
            i += 1
            continue
        name = os.path.basename(token)
        if name not in PREFIX_COMMANDS:
            break
        i += 1
        value_options = PREFIX_VALUE_OPTIONS.get(name, set())
        while i < len(tokens) and (tokens[i].startswith("-") or ASSIGNMENT.match(tokens[i])):
            i += 2 if tokens[i] in value_options else 1
        if name == "nice" and i < len(tokens) and re.match(r"^-?\d+$", tokens[i]):
            i += 1
    return tokens[i:]


def _cmd(tokens: Sequence[str]) -> str:
    return os.path.basename(tokens[0]) if tokens else ""


def _short_flags(token: str) -> str:
    """Return the letters of a short-option cluster ("-rf" -> "rf"), else ""."""
    if token.startswith("-") and not token.startswith("--") and len(token) > 1:
        return token[1:]
    return ""


def _has_flag(args: Sequence[str], short: str, longs: Sequence[str] = ()) -> bool:
    for arg in args:
        if arg == "--":
            break
        if arg in longs or any(arg.startswith(l + "=") for l in longs):
            return True
        if short and short in _short_flags(arg):
            return True
    return False


GIT_GLOBAL_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def git_subcommand(tokens: Sequence[str]) -> Tuple[str, List[str]]:
    """For a git invocation return (subcommand, args); ("", []) otherwise."""
    if _cmd(tokens) != "git":
        return "", []
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in GIT_GLOBAL_VALUE_OPTIONS else 1
    if i >= len(tokens):
        return "", []
    return tokens[i], list(tokens[i + 1 :])


def _positionals(args: Sequence[str], value_options: Sequence[str] = ()) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            out.extend(args[i + 1 :])
            break
        if arg.startswith("-") and arg != "-":
            i += 2 if arg in value_options else 1
            continue
        out.append(arg)
        i += 1
    return out


# ---------------------------------------------------------------------------
# Shared predicates
# ---------------------------------------------------------------------------

PROTECTED_BRANCHES = {"main", "master"}
ENV_EXCEPTIONS = {".env.example", ".env.sample", ".env.template"}
PRIVATE_KEY_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
LOCKFILES = {
    "apm.lock.yaml",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "uv.lock",
    "poetry.lock",
    "Cargo.lock",
}


def _normalize_path(path: str) -> str:
    path = path.replace("\\", "/")
    return path if path.startswith("/") else "/" + path


def is_secret_file(path: str) -> bool:
    name = os.path.basename(path.replace("\\", "/"))
    if name in ENV_EXCEPTIONS:
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name in PRIVATE_KEY_NAMES:
        return True
    return name.endswith(".pem") or name.endswith(".key")


# ---------------------------------------------------------------------------
# Rule predicates (segment scope receives tokens with wrappers stripped)
# ---------------------------------------------------------------------------

RM_DANGEROUS_TARGETS = {
    "/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "${HOME}", "${HOME}/",
    ".", "./", "./*", "..", "../", "*",
}


def rm_catastrophic(tokens: List[str]) -> bool:
    if _cmd(tokens) != "rm":
        return False
    args = tokens[1:]
    if not _has_flag(args, "r", ("--recursive",)) and not _has_flag(args, "R"):
        return False
    return any(arg in RM_DANGEROUS_TARGETS for arg in _positionals(args))


PUSH_VALUE_OPTIONS = ("--repo", "-o", "--push-option", "--receive-pack", "--exec")


def _push_parts(tokens: List[str]) -> Optional[Tuple[List[str], bool, bool, bool]]:
    """Return (args, force, delete, protected) for ``git push``, else None."""
    sub, args = git_subcommand(tokens)
    if sub != "push":
        return None
    positionals = _positionals(args, PUSH_VALUE_OPTIONS)
    refspecs = positionals[1:]
    force = _has_flag(args, "f", ("--force", "--force-with-lease", "--force-if-includes"))
    force = force or any(ref.startswith("+") for ref in refspecs)
    delete = _has_flag(args, "d", ("--delete",)) or any(ref.startswith(":") for ref in refspecs)
    protected = False
    for ref in refspecs:
        dest = ref.lstrip("+").split(":")[-1]
        if dest.startswith("refs/heads/"):
            dest = dest[len("refs/heads/") :]
        if dest in PROTECTED_BRANCHES:
            protected = True
    return args, force, delete, protected


def push_force_protected(tokens: List[str]) -> bool:
    parts = _push_parts(tokens)
    return bool(parts and parts[1] and parts[3])


def push_delete(tokens: List[str]) -> bool:
    parts = _push_parts(tokens)
    return bool(parts and parts[2])


def push_force(tokens: List[str]) -> bool:
    parts = _push_parts(tokens)
    return bool(parts and parts[1])


def push_protected(tokens: List[str]) -> bool:
    parts = _push_parts(tokens)
    return bool(parts and parts[3])


COMMIT_VALUE_SHORT = "mFCct"  # short options of git commit that take a value


def skips_git_hooks(tokens: List[str]) -> bool:
    sub, args = git_subcommand(tokens)
    if sub not in ("commit", "push", "merge", "rebase", "am"):
        return False
    if "--no-verify" in args:
        return True
    if sub != "commit":
        return False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            break
        letters = _short_flags(arg)
        if letters:
            for pos, letter in enumerate(letters):
                if letter == "n":
                    return True
                if letter in COMMIT_VALUE_SHORT:
                    if pos == len(letters) - 1:
                        i += 1  # value is the next token
                    break
        i += 1
    return False


def disk_destruction(tokens: List[str]) -> bool:
    cmd = _cmd(tokens)
    if cmd.startswith("mkfs"):
        return True
    if cmd == "dd":
        for arg in tokens[1:]:
            if arg.startswith("of=/dev/") and arg not in (
                "of=/dev/null", "of=/dev/stdout", "of=/dev/stderr", "of=/dev/zero"
            ):
                return True
    if cmd in ("chmod", "chown") and _has_flag(tokens[1:], "R", ("--recursive",)):
        return "/" in _positionals(tokens[1:])
    return False


FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:")
RAW_DEVICE_WRITE = re.compile(r">\s*/dev/(sd|hd|vd|xvd|nvme|disk|mmcblk)")


def command_disk_destruction(command: str) -> bool:
    return bool(FORK_BOMB.search(command) or RAW_DEVICE_WRITE.search(command))


READ_COMMANDS = {"cat", "less", "more", "head", "tail", "bat", "batcat", "nl", "xxd", "strings", "od"}


def prints_secret(tokens: List[str]) -> bool:
    if _cmd(tokens) not in READ_COMMANDS:
        return False
    return any(is_secret_file(arg) for arg in _positionals(tokens[1:], ("-n", "-c")))


def gh_repo_delete(tokens: List[str]) -> bool:
    return _cmd(tokens) == "gh" and tokens[1:3] == ["repo", "delete"]


def destructive_git(tokens: List[str]) -> bool:
    sub, args = git_subcommand(tokens)
    if sub == "reset":
        return "--hard" in args
    if sub == "clean":
        return _has_flag(args, "f", ("--force",))
    if sub == "checkout":
        return "--" in args or "." in args
    if sub == "restore":
        staged = _has_flag(args, "S", ("--staged",))
        worktree = _has_flag(args, "W", ("--worktree",))
        return worktree or not staged
    if sub == "branch":
        if _has_flag(args, "D"):
            return True
        return _has_flag(args, "d", ("--delete",)) and _has_flag(args, "f", ("--force",))
    return False


def release_or_deploy(tokens: List[str]) -> bool:
    cmd = _cmd(tokens)
    if cmd == "gh":
        return tokens[1:3] in (["pr", "merge"], ["release", "create"])
    if cmd in ("npm", "pnpm", "yarn"):
        return "publish" in tokens[1:2]
    if cmd == "vercel":
        return "--prod" in tokens or "--production" in tokens
    return False


def privilege_escalation(raw_tokens: List[str]) -> bool:
    i = 0
    while i < len(raw_tokens) and ASSIGNMENT.match(raw_tokens[i]):
        i += 1
    return i < len(raw_tokens) and os.path.basename(raw_tokens[i]) in ("sudo", "doas")


PIPE_TO_SHELL = re.compile(
    r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+(-\S+\s+)*)?(env\s+)?(ba|z|da|k|fi)?sh\b"
)


def pipes_remote_script(command: str) -> bool:
    return bool(PIPE_TO_SHELL.search(command))


def writes_secret(path: str) -> bool:
    return is_secret_file(path) or "/.ssh/" in path


def writes_git_internals(path: str) -> bool:
    return "/.git/" in path


def writes_lockfile(path: str) -> bool:
    return os.path.basename(path) in LOCKFILES


def writes_harness(path: str) -> bool:
    return (
        path.endswith("/.claude/settings.json")
        or path.endswith("/.claude/settings.local.json")
        or "/.github/hooks/" in path
    )


RULES: List[Rule] = [
    Rule("D1", "deny", "segment", rm_catastrophic,
         "Recursive rm on /, ~, $HOME, . or * is never allowed."),
    Rule("D2", "deny", "segment", push_force_protected,
         "Force-pushing to main/master is never allowed."),
    Rule("D3", "deny", "segment", skips_git_hooks,
         "Skipping git hooks (--no-verify / -n) is not allowed; fix the hook failure instead."),
    Rule("D4", "deny", "segment", disk_destruction,
         "Disk or system destructive command."),
    Rule("D4", "deny", "command", command_disk_destruction,
         "Disk or system destructive command."),
    Rule("D5", "deny", "segment", prints_secret,
         "Printing secret files (.env, private keys) into the transcript is not allowed."),
    Rule("D9", "deny", "segment", gh_repo_delete,
         "Deleting a repository is not allowed."),
    Rule("A1", "ask", "segment", destructive_git,
         "Destructive git operation that discards work; confirm with the user."),
    Rule("A1", "ask", "segment", push_delete,
         "Deleting a remote branch; confirm with the user."),
    Rule("A2", "ask", "segment", push_force,
         "Force push rewrites remote history; confirm with the user."),
    Rule("A3", "ask", "segment", push_protected,
         "Pushing directly to main/master bypasses PR review; confirm with the user."),
    Rule("A4", "ask", "segment", release_or_deploy,
         "Merge, release, publish or production deploy; confirm with the user."),
    Rule("A5", "ask", "raw_segment", privilege_escalation,
         "Running with elevated privileges; confirm with the user."),
    Rule("A5", "ask", "command", pipes_remote_script,
         "Piping a remote script into a shell; confirm with the user."),
    Rule("D6", "deny", "path", writes_secret,
         "Writing secret files (.env, private keys, ~/.ssh) is not allowed."),
    Rule("D7", "deny", "path", writes_git_internals,
         "Editing .git/ internals directly is not allowed; use git commands."),
    Rule("D8", "deny", "path", writes_lockfile,
         "Lockfiles are generated; run the package manager instead of editing them."),
    Rule("A6", "ask", "path", writes_harness,
         "Editing agent harness settings or hooks; confirm with the user."),
]

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}


def _inline_scripts(segments: List[List[str]]) -> List[str]:
    """Return scripts passed via ``bash -c '<script>'`` so they are checked too."""
    scripts: List[str] = []
    for tokens in segments:
        stripped = strip_prefix(tokens)
        if _cmd(stripped) in SHELLS:
            for i, arg in enumerate(stripped[1:-1], start=1):
                if "c" in _short_flags(arg):
                    scripts.append(stripped[i + 1])
                    break
    return scripts


def _matches(action: Action, depth: int = 0) -> List[Rule]:
    if action.kind == "write":
        path = _normalize_path(action.value)
        return [r for r in RULES if r.scope == "path" and r.check(path)]
    command = action.value
    segments, _ = split_segments(command)
    hits = [r for r in RULES if r.scope == "command" and r.check(command)]
    for tokens in segments:
        stripped = strip_prefix(tokens)
        for rule in RULES:
            if rule.scope == "segment" and stripped and rule.check(stripped):
                hits.append(rule)
            elif rule.scope == "raw_segment" and rule.check(tokens):
                hits.append(rule)
    if depth < 3:
        for script in _inline_scripts(segments):
            hits.extend(_matches(Action("shell", script), depth + 1))
    return hits


def evaluate(action: Action) -> Optional[Decision]:
    hits = _matches(action)
    for wanted in ("deny", "ask"):
        for rule in hits:
            if rule.decision == wanted:
                return Decision(rule.decision, rule.id, rule.reason)
    return None
