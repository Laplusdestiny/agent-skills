# Review workflows (1. Parallel multi-review · 2. Cross-review · 5. UI/design review)

All three share one loop: **pin the target → review it yourself → ask the others in parallel →
verify every claim → consensus table** (format in SKILL.md) **→ HTML report → follow-up rounds
on the user's feedback** (`references/report.md`).

## Contents
- Shared steps
- Reviewer prompt template
- Workflow 1: Parallel multi-review
- Workflow 2: Cross-review
- Workflow 5: UI/design review

## Shared steps

1. **Pin the target.** Decide exactly what is under review and how it maps to script flags:
   - Branch / PR vs. its base → `--diff-base <base>` (for a GitHub PR, check it out or fetch
     the head first; `gh pr checkout <n>` in a scratch worktree if the user's tree is dirty)
   - Uncommitted work → `--uncommitted`
   - Specific files or a design doc with no diff → no diff flag; name the paths in the prompt
   If the target is ambiguous ("review my changes" on a branch that also has uncommitted
   edits), ask which one rather than guessing.
2. **Review it yourself first** and jot down your findings (file:line, severity, one line
   each). This is your independent column in the table. Do it before reading their output.
3. **Write the reviewer prompt** (template below) to a scratch file. Don't mention your
   findings in it.
4. **Run** `council-ask.sh` with both agents. For a general bug hunt on a diff, add
   `--codex-builtin` so Codex uses its tuned reviewer; drop it when the review has a specific
   focus (security, performance, an API contract), since the built-in reviewer ignores the
   prompt.
5. **Verify each finding** — open the code at the cited line and decide Confirmed / False
   positive / Your call. Merge duplicates (same root cause = one row, even if worded
   differently). Watch for findings about code that isn't in the diff; they may be valid
   pre-existing issues, but label them as such.
6. **Write `report.json` and render the HTML report** (`references/report.md`). It holds
   every finding, including the ones that failed verification and the agents that failed or
   timed out.
7. **Reply** with the short consensus table and the report's path, then wait; whatever the
   user sends back starts a follow-up round (`references/report.md`).

## Reviewer prompt template

Adapt, don't copy blindly; keep it short. The script appends the diff path and a read-only
reminder automatically.

```markdown
You are reviewing a code change in <repo / component, one line on what it does>.

Intent of the change: <what the author was trying to achieve, from the PR description or user>
Focus: <correctness and bugs | security | performance | API compatibility | ...>
Out of scope: <style nits / generated files / ...>

Report each issue as:
- [High|Med|Low] path/to/file:line — the problem — why it matters (a concrete failing input or
  scenario if you can) — suggested fix

Only report issues you can tie to specific code. If you find nothing significant, say
"No significant issues" rather than inventing minor ones.
```

## Workflow 1: Parallel multi-review

The default when the user asks for a review "from codex and agy" or "from other AIs". Both
agents get the same prompt and the same `diff.patch`, so differences in what they report are
differences in judgment, not in input.

For very large diffs (thousands of lines), consider splitting: give agy the whole thing (large
context is its strength) and give Codex the riskiest files by path in the prompt, or run the
built-in reviewer per directory. Say in the report how the work was split.

## Workflow 2: Cross-review

The rule: **whoever wrote the change doesn't review it.** Pick reviewers from who authored it:

| Author | Reviewers |
|---|---|
| Claude (this session) | Codex + agy |
| Codex (via delegation) | agy + Claude |
| agy (via delegation) | Codex + Claude |
| The user / unknown | All three (that's Workflow 1) |

Cross-review naturally follows a delegation: after `council-delegate.sh` produces
`changes.patch`, run `council-ask.sh --agents <the-other-one> --cwd <worktree> --uncommitted`
against the delegate's worktree (the patch is uncommitted there), while you do your own review
of the same patch. Feed confirmed issues back to the author — for a delegate, a follow-up
round with `council-delegate.sh --reuse` and a task file listing the fixes; for your own code,
fix it yourself.

Who asked for the cross-review decides how it ends:
- **The user asked for it** ("have the others check what you just wrote"): it ends like any
  review — HTML report, short table, wait for feedback. Fixing what it found is a new task.
- **You ran it as a check inside a delegation** (`delegate.md` step 5): no HTML report and no
  stop. Verify the findings, send the confirmed ones back through `--reuse`, and fold what
  was found and fixed into the delegation's own report to the user.

When Claude is the author, be especially honest in the Claude column: list what you were
unsure about while writing it, and don't mark the reviewers' findings as false positives
without checking — it's your own blind spot they're probing.

## Workflow 5: UI/design review

**Inputs** can be screenshots, exported mockups (PNG/PDF), or a running page. Collect them as
files first:
- Live page: capture screenshots yourself (e.g. a Playwright/browser MCP if available, or
  ask the user) at the viewport sizes that matter — desktop and mobile at least. Don't count
  on agy's browser agent from the CLI; check `agy --help` if you want to try it, and fall back
  to screenshots if it isn't there.
- Implementation vs. design: put the mockup and the screenshot side by side as two `--image`
  arguments and say which is which in the prompt.

**Roles**: agy is the primary reviewer here (visual judgment, multimodal); Codex reviews the
same images via `-i` and is often sharper on whether the *code* behind it (CSS, component
structure) explains what's wrong. Review the images yourself too — you can read image files
directly.

**Prompt focus** — ask for concrete, located observations, not taste:
- Visual hierarchy: is the primary action/content obvious at a glance?
- Spacing and alignment consistency; grid breaks
- Typography: scale, line length, contrast
- Accessibility: color contrast (estimate WCAG AA), touch target size, focus states, text in images
- States: empty, loading, error, long content, overflow
- Fidelity to the mockup: list each visible difference with location
- Consistency with the existing design system / neighboring screens (attach one for reference)

Ask reviewers to locate each issue ("top-right header, the 'Save' button") so you can verify
it in the image. In the consensus table, replace `file:line` with that location, and add the
CSS/component file when someone traced it to code.
