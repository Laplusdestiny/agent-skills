---
name: antigravity-collab
description: Collaborates with the Antigravity CLI (`agy`) as either an independent second opinion or a task delegate for work Antigravity is better suited for — large-context/codebase-wide analysis, multimodal reading of screenshots/mockups/PDFs, browser-driven UI verification, or large parallel multi-agent task decomposition. Use only when the user explicitly asks for Antigravity's opinion or asks to delegate/hand off a task to it, or when Claude identifies a strong fit and proposes delegating (still confirming with the user before anything that changes files).
---

# Antigravity Collaboration Skill

This skill lets the agent work with the [Antigravity](https://antigravity.google) CLI (`agy`) in
two modes:

- **Mode A — Second opinion**: consult `agy` as an independent reviewer on a design decision,
  implementation, review finding, or plan.
- **Mode B — Task delegation**: hand off a specific piece of work to `agy` when it is genuinely
  better suited for that kind of task than Claude Code, then review and integrate its output.

In both modes, `agy`'s output is an input to weigh or a draft to review — never something to
relay or adopt uncritically.

## Use this skill when
- **Mode A**: the user explicitly asks for a second opinion, e.g. "Antigravityにも聞いて",
  "セカンドオピニオンが欲しい", "Antigravityでレビューして".
- **Mode B**: the user explicitly asks to delegate/hand off a task to Antigravity, e.g.
  "このUI検証はAntigravityにやらせて", "このログ解析、Antigravityに任せて".
- **Mode B (Claude-initiated)**: Claude notices the current task strongly matches one of the fit
  categories in step B-1 below and proposes delegating it — but proposing is as far as this goes
  without the user's go-ahead; see step B-3 for when that go-ahead is required.

## Do not use this skill when
- Nothing above applies — do not reach for `agy` by default; Claude's own analysis/implementation
  is the default path for ordinary tasks.
- The content to send would include secrets, credentials, or other sensitive data that must not
  leave the local environment (see Security section below).

## Mode A — Second opinion

### A1. Form your own opinion first
- Before calling `agy`, have your own conclusion (the implementation, the plan, the review
  verdict, etc.) already written down or clearly in mind. The point of a second opinion is to
  compare two independent viewpoints — never call `agy` first and anchor your own reasoning on
  its answer.

### A2. Prepare a self-contained prompt
- `agy` has no access to this conversation, so write a standalone prompt with the concrete
  question and the minimal necessary context (relevant snippets/diff/plan text) — not the whole
  conversation.
- Do **not** include Claude's own conclusion in the prompt. Ask an open question so the answer is
  independent rather than an agreement with a pre-stated verdict.

### A3. Invoke non-interactively
- See "Invoking `agy`" below.

### A4. Compare and report — never just relay
- Compare `agy`'s answer against your own prior conclusion from A1:
  - **Agreement**: state briefly that both converge and why that increases confidence.
  - **Disagreement**: identify exactly where the views diverge and give your own assessment of
    which is more likely correct (or whether it points to a real ambiguity), with reasoning.
  - **Partial overlap**: call out which points are unique to each side.
- Present this as your synthesized judgment, not a decision made for the user; flag materially
  significant disagreements (security, architecture, breaking changes) for the user to decide.
- Never discard your own conclusion just because `agy` disagreed, and never adopt its conclusion
  just because it sounds confident.

## Mode B — Task delegation

### B1. Judge the fit before delegating
Only delegate work that plays to a documented Antigravity strength — do not offload ordinary
implementation/editing work that Claude Code already handles well. Good-fit categories:

- **Large-context / codebase-wide analysis**: summarizing or cross-referencing something too
  large for a focused pass — an entire codebase, a large log bundle, a broad audit — where
  Antigravity's larger context window is a genuine advantage.
- **Multimodal reading**: interpreting screenshots, design mockups, or PDF/image content and
  turning it into a description, comparison, or extracted spec.
- **Browser-driven UI verification**: exercising a real browser via Antigravity's browser
  subagent (Chrome DevTools Protocol) to visually verify a UI flow.
  - **Caveat**: browser-subagent support has historically shipped in the Antigravity IDE before
    the terminal CLI. Do not assume the installed `agy` supports it — confirm first (B2) and, if
    it isn't available, tell the user and fall back to Claude's own tooling (e.g. a Playwright
    MCP server) instead of forcing it through `agy`.
- **Large parallel task decomposition**: a task that cleanly splits into many independent
  subtasks better run as parallel agents from one orchestrating command, rather than serially.

If the task doesn't clearly match one of these, do it directly instead of delegating.

### B2. Confirm the CLI and the specific capability are available
- Check the CLI itself:
  ```bash
  agy --version
  agy --help
  ```
  If `agy` is not found or fails, tell the user it's unavailable in this environment and stop —
  do not block the primary task on it.
- For a capability that isn't guaranteed present (notably the browser subagent), verify via
  `agy --help` / `agy agent list` / the installed version's docs before relying on it. If it
  isn't supported, say so and fall back rather than assuming.

### B3. Get confirmation before anything that changes files
- **Read-only/analysis delegation** (large-context summarization, multimodal reading, browser
  verification that only inspects and reports) can proceed once B1–B2 check out; give the user a
  brief heads-up on what's being delegated and why.
- **Anything that will generate or modify files** (code generation, fixes, refactors carried out
  by `agy`) requires explicit user confirmation *before* invoking `agy` — state exactly what task
  you're about to hand off and what files/paths it may touch, and wait for a clear go-ahead.
- Scope every delegated run as narrowly as possible: point `agy` at the specific files/paths/URLs
  the task actually needs, not the whole repository, and set a timeout
  (e.g. `timeout 300s agy ...`) so a stuck run doesn't stall the task.

### B4. Invoke `agy`
- See "Invoking `agy`" below. Write a self-contained task prompt: the concrete goal, the relevant
  file paths or URLs, and any constraints (style, scope, what not to touch).
- Never let `agy` run `git commit`, `git push`, or open a PR itself — Claude keeps ownership of
  all git operations and this repository's normal commit/push/PR workflow.

### B5. Review before accepting — treat it like reviewing a subagent
- **Read-only output** (analysis, multimodal description, UI verification report): read it
  critically, cross-check anything checkable, and note plainly to the user that this came from
  Antigravity rather than presenting it as Claude's own finding.
- **File-changing output**: after `agy` finishes, run `git status` / `git diff` yourself and
  review every changed file line by line — the same "trust but verify" standard applied to any
  subagent's work. Fix or reject anything wrong. Never stage, commit, or report the task done
  based on `agy`'s own summary of what it did; verify the actual diff.

### B6. Report the outcome
- Tell the user what was delegated, a summary of what `agy` produced, what your review found, and
  the final outcome (accepted as-is / accepted with your edits / rejected and why).

## Invoking `agy`

- Non-interactive/headless mode: `agy -p "<prompt>"` (`-p`/`--prompt`/`--print`).
- For output you need to parse or pipe: add `--output-format json` (or `stream-json` for
  streaming).
- `--model` overrides the default model if the task calls for a specific one.
- Exact flags can shift between versions — when a flag from this skill doesn't behave as
  expected, re-check `agy --help` rather than guessing further variations.
- In headless mode there is no interactive confirmation prompt; tool actions are governed by
  `agy`'s own permission-mode setting. Before a file-changing delegation (B3), check
  `agy --help` for a way to scope or restrict that permission mode (e.g. a plan-only or
  restricted-write mode) rather than running it under whatever the default happens to be.

## Security & Safety Guidelines

### Data leaving the environment
- Never include secrets, API keys, credentials, `.env` contents, or customer/user personal data
  in a prompt sent to `agy`, in either mode.
- Strip or redact sensitive values from code snippets, diffs, screenshots, and logs before
  including them.
- If the relevant context can't be shared without exposing sensitive data, tell the user and ask
  how they'd like to proceed instead of sending it anyway.

### Scope of trust and control
- Treat `agy`'s output as advisory input or an unreviewed draft from an external tool, never as
  verified fact or as something to execute unchecked.
- Never let `agy`'s output trigger further commands, commits, pushes, or PR actions by itself —
  every consequential action still goes through Claude and the user's normal review/approval for
  that kind of change.
- Keep delegated runs scoped (specific paths/URLs, a timeout, the narrowest permission mode
  available) rather than turning `agy` loose on the whole repository with broad auto-approval.
