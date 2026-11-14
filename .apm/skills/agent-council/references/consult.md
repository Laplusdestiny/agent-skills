# Workflow 4: Consultation (design / architecture / approach)

Gather independent opinions on a decision that isn't (yet) a diff: which library, how to
structure a module, whether a migration plan is safe, how to model some data.

## Steps

1. **Frame the decision.** Write down the question, the realistic options (including "do
   nothing" when relevant), and the constraints that actually bind: scale, team skills,
   deadlines, compatibility, existing code. If the user hasn't given enough to judge, ask
   them first — the council can't make up for missing requirements.
2. **Take your own position** with reasoning, before asking anyone.
3. **Prompt both agents neutrally.** Present the options in a fixed order without signalling a
   favorite, and point them at the relevant files so they ground their answer in the actual
   codebase:

   ```markdown
   We need to decide: <question>.

   Context: <system, relevant files by path, current state>
   Constraints: <the binding ones>
   Options under consideration:
   A. <option>
   B. <option>
   (Propose another if you think both are wrong.)

   Give: your recommendation, the 2–3 reasons that decide it, the main risk of your choice
   and how to mitigate it, and what new information would change your mind.
   ```
   Run `council-ask.sh --prompt-file ... --out-dir ...` (no diff flags).
4. **Optional rebuttal round** — only if the members split on something consequential. Send
   each the *other's* strongest argument and ask whether it changes their view. One round
   only; beyond that it's just cost.
5. **Report** with the consensus-table shape adapted to options:

   ```markdown
   ## Council consultation: <question>

   | Option | Claude | Codex | agy |
   |---|---|---|---|
   | A. ... | ✓ recommended | ✓ | – |
   | B. ... | – | – | ✓ recommended |

   **Where they agree:** ...
   **Where they split, and why:** <the real crux — usually a differing assumption; name it>
   **My recommendation:** <choice + reasons, including what in the others' answers changed or
   reinforced your view>
   **Decision for you:** <the question the user must answer, e.g. "is 3× write volume within a
   year realistic?">
   ```

6. **Render the HTML report and wait for feedback** (`references/report.md`): `kind` is
   `consultation`, each option carries the stance and reasoning of every member who answered,
   "My recommendation" becomes `recommendation`, and "Decision for you" becomes `decisions`. The user's answer to a decision is the usual trigger for a
   follow-up round — rework the recommendation with it rather than re-running the council.

A split between the agents usually means one of them is assuming something about requirements
that nobody stated. Surface that assumption as a question to the user — that's often the most
valuable output of the whole exercise.
