# CLI reference and verified quirks

The scripts encode all of this; read it when calling the CLIs by hand or debugging a failure.
Verified against `codex-cli 0.167.0` and `agy 1.5.3`. Flags drift between versions — when
something here doesn't match, check `codex exec --help` / `agy --help` instead of guessing
variations.

## Codex (`codex`)

| Purpose | Command |
|---|---|
| Read-only question | `codex exec -s read-only --ephemeral -C <dir> -o <answer.md> - < prompt.md` |
| Built-in diff review | `codex exec review --base <ref> \| --uncommitted \| --commit <sha> -c 'sandbox_mode="read-only"' --ephemeral -o <answer.md>` |
| Implementation | `codex exec -s workspace-write -C <worktree> -o <summary.md> - < task.md` |
| Attach images | `-i <file>` (repeatable) |
| Pick model | `-m <model>` (omit to use `~/.codex/config.toml`) |
| Structured output | `--output-schema <schema.json>` |

Quirks:
- `codex exec review` **rejects a custom PROMPT together with `--base`/`--uncommitted`**
  ("Usage: ... [PROMPT]" error, exit 2). For a focused review, use plain `codex exec -s
  read-only` with a prompt that points at a diff file instead.
- `-` as the prompt reads it from stdin; the final message goes to the `-o` file, while
  stdout/stderr carry the progress log.
- `--ephemeral` keeps one-off consultations out of the session history.
- `-s workspace-write` lets Codex run commands (tests) inside its sandbox, but writes are
  confined to the working dir (`-C`).

## Antigravity (`agy`)

| Purpose | Command |
|---|---|
| Read-only question | `agy --mode plan --model <m> --output-format json -p="<prompt>"` |
| Implementation | `agy --mode accept-edits --model <m> --output-format json -p="<prompt>"` (run with cwd = worktree) |
| Read files outside cwd | `--add-dir <dir>` (repeatable) |
| List models | `agy models` |
| Time limit | `--print-timeout 600s` (the scripts use `timeout` instead) |

JSON output fields: `.status` (`SUCCESS` …), `.response` (the answer text),
`.denied_actions` (tool calls refused in headless mode), `.usage`, `.conversation_id`.

Quirks:
- **Attach the prompt to the flag: `-p="..."`.** `-p --mode plan "..."` makes `--mode` the
  prompt (agy errors out), and `-p -` sends a literal `-` — it does not read stdin.
- **Headless mode auto-denies shell commands.** You'll see an empty `.response` plus
  `denied_actions: [{"action":"command"...}]` and a stderr note. agy can still *read* files,
  which is why the scripts pre-generate `diff.patch` instead of asking agy to run `git diff`.
  Allow-rules via `--settings <file.json>` with `{"permissions":{"allow":["command(git diff)"]}}`
  work only for the exact command string — wildcards like `command(git diff*)` did not match —
  so they're rarely worth it. Don't reach for `--dangerously-skip-permissions`.
- **Pin a Gemini model.** `agy models` also lists Claude models; asking Claude for an
  independent opinion via agy defeats the purpose. The scripts pick the first `gemini-*-high`
  model unless `AGENT_COUNCIL_AGY_MODEL` is set.
- Browser-agent support has historically landed in the Antigravity IDE before the CLI. Don't
  plan a workflow around it without checking the installed version.

## Script exit codes

| Script | Code | Meaning |
|---|---|---|
| council-ask.sh | 0 | at least one agent answered |
| | 1 | every selected agent failed / timed out / was unavailable (see `<agent>.status`, `<agent>.log`) |
| | 2 | bad arguments |
| | 3 | review target given but the diff is empty |
| council-delegate.sh | 0 | delegate finished and produced changes |
| | 1 | delegate failed or timed out (partial changes may still be in the patch) |
| | 2 | bad arguments / not a git repo / worktree already exists |
| | 4 | CLI unavailable |
| | 5 | no changes produced |
