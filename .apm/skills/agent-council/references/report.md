# HTML report and follow-up rounds

Every review, cross-review, UI review, and consultation the user asked for ends the same way:
**write `report.json` → render it → hand the page to the user → take their feedback into
another round**. The page is the complete result, readable at the user's own pace, shareable,
and open to comments; the chat gets the short consensus table from SKILL.md. (A cross-review
you run as a check inside a delegation is not one of these — see `review.md`, Workflow 2.)

## Contents
- Steps
- report.json
- Follow-up rounds

## Steps

1. **Write `<out-dir>/report.json`** after verification, in the same directory as the agents'
   raw answers. Write every text field in the report language (below), for a reader who was
   not in this conversation: full sentences, no session shorthand, each finding understandable
   on its own.
2. **Render it:**

   ```bash
   python3 <skill-dir>/scripts/council-report.py --input <out-dir>/report.json --lang ja [--open]
   ```

   `--lang` sets the page's headings and labels. Use the language the user asked for; if they
   didn't name one, use the language they are writing in. `ja` and `en` are built in; for any
   other language pass `--labels FILE` with translated label keys (copy the `en` block from
   the script). The script validates the JSON and exits 2 with a list of problems — fix the
   JSON rather than working around it.
3. **Hand it over.** In the chat: the short consensus table (High and Med findings and
   everything marked "your call", with the same ids as the page; the rest as a count), then
   the absolute path of `report.html`, then one line inviting feedback — they can comment on items in the page and
   paste the result of "Copy feedback", or just reply in the chat. Then stop and wait.

The page embeds the agents' raw answers (`codex.md`, `agy.md`, `prompt.sent.md` from the
directory of `--input`, or from each `--raw-dir`). Pass `--no-raw` when the user plans to share
the page beyond people who may see those answers.

## report.json

```json
{
  "kind": "review",
  "lang": "ja",
  "title": "割引機能ブランチのレビュー",
  "subject": "feature/discounts を main と比較(3ファイル、+48/-6)",
  "round": 1,
  "summary": "マージ前に直すべき問題が2件あります。...",
  "reviewers": [
    {"id": "claude", "label": "Claude", "status": "ok"},
    {"id": "codex", "label": "Codex", "model": "default", "status": "ok"},
    {"id": "agy", "label": "agy", "model": "gemini-3-pro-high", "status": "timeout"}
  ],
  "findings": [
    {
      "id": "F1",
      "severity": "high",
      "title": "トークンを == で比較している",
      "location": "shop/auth.py:42",
      "detail": "何が問題で、どんな入力・状況で実害が出るか。",
      "raised_by": ["claude", "codex"],
      "verdict": "confirmed",
      "verdict_note": "どう確かめたか、なぜその判定か。",
      "suggested_fix": "`hmac.compare_digest` を使う。"
    }
  ],
  "decisions": [
    {"id": "D1", "question": "ユーザーが答える問い", "context": "なぜそれで結論が変わるか。"}
  ],
  "agreements": "...",
  "disagreements": "どこで割れたか、どちらを支持するか、その理由。",
  "not_covered": "失敗したエージェント、誰も見ていない範囲。",
  "history": []
}
```

| Field | Rules |
|---|---|
| `kind` | `review` · `ui-review` · `consultation` |
| `title`, `summary`, `reviewers` | Required. `summary` is the conclusion in 2–4 sentences: what the user should do next. |
| `reviewers[]` | `id` and `status` (`ok` · `failed` · `timeout` · `unavailable`) required; `label` and `model` optional. List every member that was asked, including the ones that didn't answer. |
| `findings[]` | `id`, `title`, `severity` (`high` `med` `low` `info`), `verdict` (`confirmed` `false_positive` `your_call`) required. `raised_by` is a list of reviewer ids (empty when the point came from the user). One entry per root cause. For UI reviews, `location` is the place on screen. |
| `options[]`, `recommendation` | Both required for `consultation`. Each option: `id`, `title`, `detail`, and `positions` keyed by reviewer id with an entry for every reviewer whose status is `ok`, each `{"stance": "recommended"｜"acceptable"｜"against"｜"", "note": "their reasoning"}`. Top-level `recommendation` is your pick and why. |
| `subject`, `agreements`, `disagreements`, `not_covered`, `lang` | Optional. `subject` is one line on what was examined; `lang` is the page language used when `--lang` isn't passed. |
| `decisions[]` | `id`, `question`, optional `context`. Everything marked `your_call` and every unstated assumption the agents split on becomes a decision here. |
| `round`, `history[]`, `findings[].updated_round` | See follow-up rounds. |

Ids (`F1`, `A`, `D1`) must be unique across the report and stay stable across rounds — the
user's feedback refers to them, in the page and in the chat. The page sorts findings by
severity and opens the ones that need attention first (High, "your call", changed this
round); the rest are collapsed under the overview table. Body fields (`summary`, `detail`,
`verdict_note`, `suggested_fix`, `context`, `note`, `recommendation`, and the three closing
sections) accept `` `code` ``, `**bold**`, and blank-line paragraphs; titles, questions, and
locations are shown literally. The script checks these rules and the types behind them.

## Follow-up rounds

The user's feedback arrives as pasted text headed "Council feedback" / "合議へのフィードバック"
with `[F1]`-style item ids, or as a plain chat reply. Either way:

1. **Sort each point by what it needs**, and do only that much:

   | The user... | Do |
   |---|---|
   | answers a decision (`D1`) | Rework the recommendation and affected verdicts yourself. No new council call. |
   | disputes a verdict or adds a fact | Re-check the code against their point. Change the verdict if they're right; if they're not, keep it and say what you checked. |
   | asks for a deeper look, a new angle, or wider scope | Run `council-ask.sh` again with a focused prompt into `<out-dir>/round-<n>/`. State the user's point as a question to examine, not as a conclusion to confirm. |
   | asks for fixes or implementation | That is a new task: handle it yourself or through `references/delegate.md`, with its usual confirmation. The report loop only updates the report. |

2. **Update `report.json`:** increment `round`; append
   `{"round": <previous round>, "feedback": "<their text, verbatim>", "response": "<what you
   checked and what changed, including points you did not adopt and why>"}` to `history`; set
   `updated_round` on every finding you changed or added; revise `summary`, `decisions`, and
   `recommendation` so the top of the page is current. Keep ids; give new items new ids.
   Keep refuted findings with their new verdict instead of deleting them.
3. **Re-render** with the same command, adding `--raw-dir <out-dir> --raw-dir
   <out-dir>/round-<n>` when a new council call produced more raw answers.
4. **Reply** with what changed in two or three lines and the path again, then wait. Don't
   repeat the table; the page marks what changed.

The loop ends when the user says they have what they need or moves on to acting on the result.
