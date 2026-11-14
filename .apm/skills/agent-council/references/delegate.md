# Workflow 3: Delegation

Hand a well-defined implementation task to Codex or agy, let it work in an isolated git
worktree, then review and integrate the result yourself. The user's working tree is never
touched until Claude applies a patch it has verified.

## Contents
- 1. Decide whether and to whom
- 2. Confirm with the user
- 3. Write the task brief
- 4. Run the delegate
- 5. Verify the patch
- 6. Integrate or discard
- 7. Report
- Variant: competing drafts

## 1. Decide whether and to whom

Delegate when it buys something — not to offload ordinary work Claude would do equally well.
Good reasons: the user asked for it; the task is self-contained and parallelizable with what
Claude is doing; the task plays to a member's strength.

| Task shape | Delegate to | Why |
|---|---|---|
| Bug fix or feature with tests to run/iterate on | **Codex** | It runs commands in its sandbox, so it can test-fix-retest |
| Mechanical change across many files (rename, API migration) | **Codex** if it needs tests to confirm, **agy** if it's a pure edit guided by codebase-wide understanding | agy holds more of the codebase at once but can't run tests headless |
| Implement from a screenshot/mockup/PDF spec | **agy** | Multimodal input is its strength; Claude runs the tests afterwards |
| Small, tightly coupled change to code Claude is mid-edit on | **Nobody** — do it yourself | The worktree starts from a commit and won't see uncommitted work |

The delegate starts from `--base` (default `HEAD`). If the task depends on uncommitted changes,
tell the user and ask whether to commit them first (on a branch) or to do the task directly.

## 2. Confirm with the user

Delegations write code, so ask before running. One short message covering:
- the task in one sentence, and which agent (with the reason)
- the files/dirs in scope
- that it runs in a separate worktree/branch (`council/<agent>/<slug>`) and nothing lands in
  their tree until Claude reviews the patch

Wait for a clear yes. A previous approval doesn't carry over to a different task.

## 3. Write the task brief

The delegate has none of this conversation. Write a brief to a scratch file:

```markdown
# Task: <one-line goal>

## Context
<what the code does today, the relevant files by path, any decisions already made>

## What to do
<the change, concretely; numbered steps if order matters>

## Scope
- In scope: <paths>
- Out of scope: <paths/behaviors to leave alone>

## Done when
- <observable criteria: tests that pass, behavior that changes, commands that succeed>
- <for Codex: the exact test command to run, e.g. `pytest tests/test_auth.py`>

## Constraints
<style conventions, no new dependencies, keep public API, etc.>
```

The script appends ground rules (stay in the worktree, don't commit, summarize what was
verified), so the brief doesn't need to repeat them.

## 4. Run the delegate

```bash
bash <skill-dir>/scripts/council-delegate.sh --agent codex --task-file brief.md \
  --name fix-token-compare --repo <repo>
```

This can take many minutes; run it in the background if the harness allows and continue with
other work. The output lists the worktree, the branch, the delegate's summary file, and
`changes.patch` with a diff stat.

Exit codes: `0` ok, `1` the delegate failed or timed out (inspect the log — partial work may
still be in the patch), `4` CLI unavailable, `5` no changes were produced.

## 5. Verify the patch

The delegate's summary is a claim; the patch is the evidence.
- Read `changes.patch` in full. Every hunk should serve the task. Flag scope creep, deleted
  tests, weakened assertions, new dependencies, and "fixed" by catching-and-ignoring.
- Run the checks yourself **in the worktree** (tests, type-check, lint), even if the summary
  says they pass — and always for agy, which couldn't run them.
- If the script warned that the delegate made commits, inspect them; the patch already
  includes them.
- For non-trivial changes, consider a cross-review (Workflow 2 in `review.md`) by the member
  who didn't write it. This one is a check on the way to finishing the delegation, so it
  doesn't produce an HTML report or wait for the user — its confirmed findings go into the
  fixes below and into your report on the delegation.

If it needs fixes: small ones, make them yourself in the worktree; larger ones, write a
follow-up brief listing exactly what's wrong and rerun with `--reuse` (same `--name`), which
keeps the delegate's previous edits. Cap it at two follow-up rounds before taking over yourself.

## 6. Integrate or discard

To integrate, apply the verified patch to the user's tree as unstaged changes:
```bash
git -C <repo> apply <out-dir>/changes.patch
```
If that fails because the user's tree moved on, retry with `--3way`; it resolves more cases
but stages what it applies, so follow it with `git -C <repo> restore --staged .` (when nothing
was staged before) to leave the user's index as it was. Then show `git status`/`git diff --stat`
and continue with the user's normal commit flow — Claude makes the commit (if the user wants
one), not the delegate.

Generated byproducts (`__pycache__`, `*.pyc`, tool caches) are left out of the patch
automatically; the script lists them in `skipped-generated.txt`. Run your own test passes with
`python3 -B` or equivalent so you don't leave new ones in the user's tree.

Clean up the worktree and branch once the patch is applied, or once the user agrees to
discard it:
```bash
git -C <repo> worktree remove <worktree>
git -C <repo> branch -D council/<agent>/<slug>
```
Don't delete a worktree whose changes haven't been applied or explicitly rejected — that's the
only copy of the delegate's work.

## 7. Report

Tell the user: what was delegated and to whom, what the delegate produced (diff stat), what
your verification found (tests run and results, issues fixed or rejected), and the outcome:
applied as-is / applied with your edits / rejected and why. Keep the delegate's summary
clearly attributed — don't present its claims as your own findings.

## Variant: competing drafts

When the user wants options ("両方に作らせて比べて"), run the same brief through both agents
with different `--name`s (e.g. `login-form-codex`, `login-form-agy`) — they run independently
and can go in parallel. Verify both patches as above, then compare: correctness, test results,
size of the change, fit with the codebase. Recommend one (or a merge of specific parts) with
reasons, and let the user choose before applying anything.
