#!/usr/bin/env python3
"""Render a council result (report.json) as one self-contained HTML page for the user.

Claude writes report.json after verifying the agents' answers; this script only lays it out.
The page shows the conclusion, the decisions left to the user, the consensus table, and the
raw agent outputs, and gives every item a comment box. "Copy feedback" turns those comments
into a text block the user pastes back into the chat to start a follow-up round.

Standard library only. Schema: references/report.md.
"""
import argparse
import datetime
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

LABELS = {
    "en": {
        "kind_review": "Council review",
        "kind_ui-review": "Council UI review",
        "kind_consultation": "Council consultation",
        "round": "Round",
        "generated": "Generated",
        "reviewers": "Council members",
        "summary": "Conclusion",
        "decisions": "Decisions for you",
        "findings": "Findings",
        "options": "Options",
        "option": "Option",
        "recommendation": "Recommendation",
        "agreements": "Where the agents agree",
        "disagreements": "Where the agents disagree",
        "not_covered": "Not covered",
        "history": "Earlier rounds",
        "feedback_given": "Your feedback",
        "response": "What changed",
        "raw": "Raw agent outputs",
        "raw_note": "Unedited answers, kept for reference. The sections above are the verified result.",
        "severity": "Severity",
        "finding": "Finding",
        "location": "Location",
        "verdict": "Verdict",
        "sev_high": "High",
        "sev_med": "Medium",
        "sev_low": "Low",
        "sev_info": "Info",
        "verdict_confirmed": "Confirmed",
        "verdict_false_positive": "False positive",
        "verdict_your_call": "Your call",
        "stance_recommended": "Recommended",
        "stance_acceptable": "Acceptable",
        "stance_against": "Against",
        "stance_none": "–",
        "status_ok": "answered",
        "status_failed": "failed",
        "status_timeout": "timed out",
        "status_unavailable": "unavailable",
        "updated": "Updated in round",
        "suggested_fix": "Suggested fix",
        "comment_placeholder": "Comment or instruction on this item (optional)",
        "feedback": "Your feedback",
        "feedback_help": "Write comments on any item above, or overall here. Then copy the "
                         "feedback and paste it into the chat: the council will take it into "
                         "account and update this report.",
        "overall_placeholder": "Overall comments, extra instructions, things to look at next",
        "copy": "Copy feedback",
        "copied": "Copied. Paste it into the chat.",
        "copy_failed": "Could not copy automatically. Select the text below and copy it.",
        "empty_feedback": "No comments yet. Write at least one comment first.",
        "clear": "Clear comments",
        "fb_title": "Council feedback",
        "fb_overall": "Overall",
        "none": "None.",
    },
    "ja": {
        "kind_review": "合議レビュー",
        "kind_ui-review": "合議UIレビュー",
        "kind_consultation": "合議による検討",
        "round": "ラウンド",
        "generated": "作成日時",
        "reviewers": "参加エージェント",
        "summary": "結論",
        "decisions": "あなたに決めてほしいこと",
        "findings": "指摘事項",
        "options": "選択肢",
        "option": "選択肢",
        "recommendation": "推奨",
        "agreements": "意見が一致した点",
        "disagreements": "意見が分かれた点",
        "not_covered": "確認できていない範囲",
        "history": "これまでのラウンド",
        "feedback_given": "いただいた意見",
        "response": "反映した内容",
        "raw": "各エージェントの生の回答",
        "raw_note": "参考用の未編集の回答です。検証済みの結果は上のセクションです。",
        "severity": "重大度",
        "finding": "指摘",
        "location": "場所",
        "verdict": "判定",
        "sev_high": "高",
        "sev_med": "中",
        "sev_low": "低",
        "sev_info": "参考",
        "verdict_confirmed": "確認済み",
        "verdict_false_positive": "誤検知",
        "verdict_your_call": "要判断",
        "stance_recommended": "推奨",
        "stance_acceptable": "許容",
        "stance_against": "反対",
        "stance_none": "–",
        "status_ok": "回答あり",
        "status_failed": "失敗",
        "status_timeout": "タイムアウト",
        "status_unavailable": "利用不可",
        "updated": "更新されたラウンド",
        "suggested_fix": "修正案",
        "comment_placeholder": "この項目への意見・指示(任意)",
        "feedback": "ご意見・追加の指示",
        "feedback_help": "上の各項目、またはここに全体への意見を書いてください。「フィードバックを"
                         "コピー」を押してチャットに貼り付けると、その内容を踏まえて追加検討し、"
                         "このレポートを更新します。",
        "overall_placeholder": "全体への意見、追加の指示、次に見てほしい点など",
        "copy": "フィードバックをコピー",
        "copied": "コピーしました。チャットに貼り付けてください。",
        "copy_failed": "自動でコピーできませんでした。下のテキストを選択してコピーしてください。",
        "empty_feedback": "まだコメントがありません。先に1件以上書いてください。",
        "clear": "コメントを消去",
        "fb_title": "合議へのフィードバック",
        "fb_overall": "全体",
        "none": "なし。",
    },
}

KINDS = ("review", "ui-review", "consultation")
SEVERITIES = ("high", "med", "low", "info")
VERDICTS = ("confirmed", "false_positive", "your_call")
STANCES = ("recommended", "acceptable", "against", "")
STATUSES = ("ok", "failed", "timeout", "unavailable")
RAW_FILES = ("codex.md", "agy.md", "prompt.sent.md")
RAW_LIMIT = 200_000  # characters per raw file; keeps the page openable


def fail(msg):
    print(f"council-report: {msg}", file=sys.stderr)
    sys.exit(2)


def validate(r):
    """Stop on anything that would silently render as a wrong or empty report."""
    errs = []

    def text(obj, key, where):
        v = obj.get(key)
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{where}: '{key}' must be a non-empty string")

    def enum(obj, key, allowed, where):
        v = obj.get(key)
        if not isinstance(v, str) or v not in allowed:
            errs.append(f"{where}: '{key}' must be one of {list(allowed)}, got {v!r}")

    def round_no(obj, key, where):
        v = obj.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
            errs.append(f"{where}: '{key}' must be a positive integer, got {v!r}")

    def items(key):
        """(where, object) for each entry of the list r[key]; other shapes are reported."""
        v = r.get(key)
        if v is None:
            return []
        if not isinstance(v, list):
            errs.append(f"report: '{key}' must be a list")
            return []
        out = []
        for i, o in enumerate(v):
            if isinstance(o, dict):
                out.append((f"{key}[{i}]", o))
            else:
                errs.append(f"{key}[{i}]: must be an object, got {type(o).__name__}")
        return out

    for key in ("title", "summary"):
        text(r, key, "report")
    enum(r, "kind", KINDS, "report")
    round_no(r, "round", "report")
    reviewers = items("reviewers")
    if not reviewers:
        errs.append("report: 'reviewers' must list the council members")
    ids, answered = set(), []
    for w, rv in reviewers:
        text(rv, "id", w)
        enum(rv, "status", STATUSES, w)
        if isinstance(rv.get("id"), str):
            if rv["id"] in ids:
                errs.append(f"{w}: duplicate reviewer id {rv['id']!r}")
            ids.add(rv["id"])
            if rv.get("status") == "ok":
                answered.append(rv["id"])
    seen = set()

    def item_id(obj, where):
        text(obj, "id", where)
        if isinstance(obj.get("id"), str):
            if obj["id"] in seen:
                errs.append(f"{where}: duplicate id {obj['id']!r}")
            seen.add(obj["id"])

    for w, f in items("findings"):
        item_id(f, w)
        text(f, "title", w)
        enum(f, "severity", SEVERITIES, w)
        enum(f, "verdict", VERDICTS, w)
        round_no(f, "updated_round", w)
        raised = f.get("raised_by", [])
        if not isinstance(raised, list):
            errs.append(f"{w}: 'raised_by' must be a list of reviewer ids")
            raised = []
        for a in raised:
            if not isinstance(a, str) or a not in ids:
                errs.append(f"{w}: raised_by has unknown reviewer id {a!r}")
    options = items("options")
    for w, o in options:
        item_id(o, w)
        text(o, "title", w)
        text(o, "detail", w)
        pos = o.get("positions")
        if not isinstance(pos, dict):
            errs.append(f"{w}: 'positions' must be an object keyed by reviewer id")
            continue
        for a, p in pos.items():
            if a not in ids:
                errs.append(f"{w}: positions has unknown reviewer id {a!r}")
            stance = p.get("stance", "") if isinstance(p, dict) else p
            if not isinstance(stance, str) or stance not in STANCES:
                errs.append(f"{w}: stance for {a} must be one of {list(STANCES)}, got {stance!r}")
        for a in answered:
            if a not in pos:
                errs.append(f"{w}: positions is missing {a!r}, who answered")
    for w, d in items("decisions"):
        item_id(d, w)
        text(d, "question", w)
    for w, h in items("history"):
        text(h, "feedback", w)
        text(h, "response", w)
        round_no(h, "round", w)
    if r.get("kind") == "consultation":
        if not options:
            errs.append("report: a consultation needs 'options'")
        text(r, "recommendation", "report")
    if errs:
        fail("invalid report.json\n  - " + "\n  - ".join(errs))


def esc(s):
    return html.escape(str(s), quote=True)


def rich(s):
    """Escaped text with `code`, **bold**, and paragraph/line breaks. No other markup."""
    if not s:
        return ""

    # One pass over both patterns, so `**` inside a code span stays literal.
    def mark(m):
        if m.group(1) is not None:
            return f"<code>{m.group(1)}</code>"
        return f"<strong>{m.group(2)}</strong>"

    out = []
    for para in re.split(r"\n\s*\n", str(s).strip()):
        t = re.sub(r"`([^`\n]+)`|\*\*([^*\n]+)\*\*", mark, esc(para))
        out.append("<p>" + t.replace("\n", "<br>") + "</p>")
    return "".join(out)


def section(sec_id, title, body):
    return f'<section id="{sec_id}"><h2>{esc(title)}</h2>{body}</section>' if body else ""


def cols(*sections):
    """Sections side by side where the window is wide enough, stacked otherwise."""
    body = "".join(sections)
    return f'<div class="cols">{body}</div>' if body else ""


def split(table, items):
    """Overview table on the left, the collapsible items it links to on the right."""
    return (f'<div class="split"><div class="table-wrap">{table}</div>'
            f'<div class="items">{items}</div></div>')


def comment_box(item_id, label, L):
    return (f'<textarea class="comment" data-id="{esc(item_id)}" data-label="{esc(label)}" '
            f'rows="2" placeholder="{esc(L["comment_placeholder"])}"></textarea>')


def render(r, L, raw, lang):
    reviewers = r["reviewers"]
    rnd = r.get("round") or 1
    name = lambda rv: rv.get("label") or rv["id"]

    members = "".join(
        f'<li><strong>{esc(name(rv))}</strong>'
        + (f' <span class="model">{esc(rv["model"])}</span>' if rv.get("model") else "")
        + f' <span class="status st-{rv["status"]}">{esc(L["status_" + rv["status"]])}</span></li>'
        for rv in reviewers)

    decisions = "".join(
        f'<div class="block" id="{esc(d["id"])}"><h3><span class="tag">{esc(d["id"])}</span>'
        f'{esc(d["question"])}</h3>'
        f'{rich(d.get("context"))}{comment_box(d["id"], d["question"], L)}</div>'
        for d in r.get("decisions") or [])

    findings_html = ""
    findings = r.get("findings") or []
    if findings:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        findings = sorted(findings, key=lambda f: order[f["severity"]])
        head = "".join(f"<th>{esc(name(rv))}</th>" for rv in reviewers)
        rows, cards = [], []
        for f in findings:
            raised = set(f.get("raised_by") or [])
            marks = "".join(
                f'<td class="mark">{"✓" if rv["id"] in raised else "–"}</td>' for rv in reviewers)
            sev = f'<span class="sev sev-{f["severity"]}">{esc(L["sev_" + f["severity"]])}</span>'
            ver = (f'<span class="verdict v-{f["verdict"]}">'
                   f'{esc(L["verdict_" + f["verdict"]])}</span>')
            loc = f'<code>{esc(f["location"])}</code>' if f.get("location") else ""
            rows.append(
                f'<tr><td><a href="#{esc(f["id"])}">{esc(f["id"])}</a></td><td>{sev}</td>'
                f'<td class="what">{esc(f["title"])}<div class="loc">{loc}</div></td>{marks}<td>{ver}</td></tr>')
            upd = (f'<span class="tag upd">{esc(L["updated"])} {esc(f["updated_round"])}</span>'
                   if f.get("updated_round") else "")
            who = ", ".join(esc(name(rv)) for rv in reviewers if rv["id"] in raised)
            fix = (f'<h4>{esc(L["suggested_fix"])}</h4>{rich(f["suggested_fix"])}'
                   if f.get("suggested_fix") else "")
            # Open what needs the reader first; the rest is one click away in the table.
            is_open = (f["severity"] == "high" or f["verdict"] == "your_call"
                       or f.get("updated_round") == rnd)
            cards.append(
                f'<details class="item" id="{esc(f["id"])}"{" open" if is_open else ""}>'
                f'<summary><span class="tag">{esc(f["id"])}</span>{sev}{ver}{upd}'
                f'<span class="ttl">{esc(f["title"])}</span></summary><div class="item-body">'
                f'<div class="meta">{loc} <span class="who">{who}</span></div>'
                f'{rich(f.get("detail"))}{rich(f.get("verdict_note"))}{fix}'
                f'{comment_box(f["id"], f["title"], L)}</div></details>')
        findings_html = split(
            f'<table><thead><tr><th>#</th><th>{esc(L["severity"])}</th>'
            f'<th>{esc(L["finding"])}</th>{head}<th>{esc(L["verdict"])}</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>', "".join(cards))

    options_html = ""
    options = r.get("options") or []
    if options:
        head = "".join(f"<th>{esc(name(rv))}</th>" for rv in reviewers)
        rows, cards = [], []
        for o in options:
            pos = o.get("positions") or {}
            cells, notes = [], []
            for rv in reviewers:
                p = pos.get(rv["id"], "")
                stance, note = (p.get("stance", ""), p.get("note", "")) if isinstance(p, dict) else (p, "")
                cells.append(f'<td class="mark"><span class="stance s-{stance or "none"}">'
                             f'{esc(L["stance_" + (stance or "none")])}</span></td>')
                if note:
                    notes.append(f"<dt>{esc(name(rv))}</dt><dd>{rich(note)}</dd>")
            rows.append(f'<tr><td><a href="#{esc(o["id"])}">{esc(o["id"])}</a></td>'
                        f'<td class="what">{esc(o["title"])}</td>{"".join(cells)}</tr>')
            cards.append(
                f'<details class="item" id="{esc(o["id"])}" open><summary>'
                f'<span class="tag">{esc(o["id"])}</span><span class="ttl">{esc(o["title"])}</span>'
                f'</summary><div class="item-body">{rich(o.get("detail"))}'
                + (f'<dl class="positions">{"".join(notes)}</dl>' if notes else "")
                + f'{comment_box(o["id"], o["title"], L)}</div></details>')
        options_html = split(
            f'<table><thead><tr><th>#</th><th>{esc(L["option"])}</th>'
            f'{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>', "".join(cards))

    history = "".join(
        f'<div class="block"><h3>{esc(L["round"])} {esc(h.get("round", i + 1))}</h3>'
        f'<h4>{esc(L["feedback_given"])}</h4><blockquote>{rich(h["feedback"])}</blockquote>'
        f'<h4>{esc(L["response"])}</h4>{rich(h["response"])}</div>'
        for i, h in enumerate(r.get("history") or []))

    raw_html = ""
    if raw:
        raw_html = f'<p class="note">{esc(L["raw_note"])}</p>' + "".join(
            f'<details><summary>{esc(label)}</summary><pre>{esc(text)}</pre></details>'
            for label, text in raw)

    feedback = (
        f'<p class="note">{esc(L["feedback_help"])}</p>'
        f'<textarea class="comment overall" data-id="overall" data-label="{esc(L["fb_overall"])}" '
        f'rows="4" placeholder="{esc(L["overall_placeholder"])}"></textarea>'
        f'<div class="actions"><button id="copy" type="button">{esc(L["copy"])}</button>'
        f'<button id="clear" type="button" class="ghost">{esc(L["clear"])}</button>'
        f'<span id="msg" role="status"></span></div>'
        f'<textarea id="fb-out" rows="8" readonly hidden></textarea>')

    body = "".join([
        cols(section("summary", L["summary"], rich(r["summary"])),
             section("decisions", L["decisions"], decisions)),
        section("options", L["options"], options_html),
        section("recommendation", L["recommendation"], rich(r.get("recommendation"))),
        section("findings", L["findings"], findings_html),
        cols(section("agreements", L["agreements"], rich(r.get("agreements"))),
             section("disagreements", L["disagreements"], rich(r.get("disagreements"))),
             section("not-covered", L["not_covered"], rich(r.get("not_covered")))),
        cols(section("feedback", L["feedback"], feedback),
             section("history", L["history"], history)),
        section("raw", L["raw"], raw_html),
    ])

    js_data = {
        "key": f'council:{r["title"]}:{rnd}',
        "title": f'{L["fb_title"]} — {r["title"]} ({L["round"]} {rnd})',
        "copied": L["copied"], "copyFailed": L["copy_failed"], "empty": L["empty_feedback"],
    }
    # \\uXXXX keeps report text from ending or re-opening the <script> element it sits in.
    data = json.dumps(js_data, ensure_ascii=False)
    for ch in "<>&":
        data = data.replace(ch, f"\\u{ord(ch):04x}")
    values = {
        "LANG": esc(lang),
        "TITLE": esc(r["title"]),
        "KIND": esc(L["kind_" + r["kind"]]),
        "SUBJECT": f'<p class="subject">{esc(r["subject"])}</p>' if r.get("subject") else "",
        "META": (f'{esc(L["round"])} {rnd} · {esc(L["generated"])} '
                 f'{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}'),
        "REVIEWERS_LABEL": esc(L["reviewers"]),
        "MEMBERS": members,
        "BODY": body,
        "DATA": data,
    }
    # A single pass: text that merely looks like a placeholder inside a value is left alone.
    return re.sub(r"@@([A-Z_]+)@@", lambda m: values.get(m.group(1), m.group(0)), PAGE)


PAGE = """<!doctype html>
<html lang="@@LANG@@">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<style>
:root {
  --bg: #fbfaf8; --field: #ffffff; --text: #1d2126; --muted: #626a73; --line: #d9d6cf;
  --link: #1f4e9c; --high: #b3261e; --med: #8a5a00; --low: #2f6b3a; --code-bg: #efede8;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17191c; --field: #1f2226; --text: #e3e1dc; --muted: #9a9891; --line: #34373c;
    --link: #8fb2f0; --high: #f08a80; --med: #e0b060; --low: #86c494; --code-bg: #26292e;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); line-height: 1.7;
  font-family: system-ui, -apple-system, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif; }
main { max-width: 1320px; margin: 0 auto; padding: 28px 24px 64px; }
header { border-bottom: 2px solid var(--text); padding-bottom: 14px; }
.kind, h2 { color: var(--muted); font-size: .8rem; font-weight: 700; letter-spacing: .08em; }
h1 { font-size: 1.5rem; line-height: 1.35; margin: 2px 0 6px; }
h2 { margin: 0 0 10px; }
h3 { font-size: 1rem; margin: 0 0 4px; }
h4 { font-size: .8rem; color: var(--muted); margin: 12px 0 2px; }
p { margin: 0 0 8px; }
.subject, .meta, .note, .loc { color: var(--muted); font-size: .88rem; }
section { margin-top: 28px; padding-top: 10px; border-top: 1px solid var(--line); min-width: 0; }
.cols { display: grid; gap: 0 36px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); }
#summary p { font-size: 1.05rem; }
.members { list-style: none; display: flex; flex-wrap: wrap; gap: 2px 22px; padding: 0; margin: 10px 0 0;
  font-size: .85rem; }
.members .model, .members .status { color: var(--muted); }
.members .st-failed, .members .st-timeout, .members .st-unavailable { color: var(--high); }
.block { padding: 10px 0; border-top: 1px solid var(--line); }
.block:first-of-type { border-top: 0; padding-top: 0; }
.tag { font: .78rem ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted); margin-right: 8px; }
.tag.upd { color: var(--link); }
.sev, .verdict, .stance { font-size: .8rem; font-weight: 700; white-space: nowrap; }
.sev::before { content: ""; display: inline-block; width: .6em; height: .6em; margin-right: .4em;
  background: currentColor; }
.sev-high, .s-against { color: var(--high); }
.sev-med, .v-your_call { color: var(--med); }
.sev-low, .s-recommended { color: var(--low); }
.sev-info, .v-false_positive, .s-none { color: var(--muted); }
.split { display: grid; gap: 20px; }
@media (min-width: 1000px) {
  .split { grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); align-items: start; gap: 36px; }
  .split > * { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow: auto; }
}
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: .78rem; white-space: nowrap; }
.mark { text-align: center; }
td.what { min-width: 12rem; }
details { border-bottom: 1px solid var(--line); padding: 8px 0; }
summary { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 10px; cursor: pointer;
  list-style: none; }
summary::-webkit-details-marker { display: none; }
summary::before { content: "+"; font-family: ui-monospace, monospace; color: var(--muted); }
details[open] > summary::before { content: "\\2212"; }
summary .tag { margin-right: 0; }
.ttl { flex: 1 1 18rem; font-weight: 600; }
.item-body { padding: 6px 0 4px 1.4rem; }
.who { margin-left: 8px; }
a { color: var(--link); }
code { background: var(--code-bg); border-radius: 3px; padding: 1px 4px; font-size: .88em;
  overflow-wrap: anywhere; }
pre { background: var(--code-bg); padding: 12px; overflow-x: auto; white-space: pre-wrap;
  overflow-wrap: anywhere; font-size: .82rem; max-height: 480px; }
blockquote { margin: 0; padding: 2px 12px; border-left: 2px solid var(--line); color: var(--muted); }
dl.positions { margin: 8px 0 0; } dt { font-weight: 700; font-size: .85rem; } dd { margin: 0 0 6px; }
textarea { width: 100%; margin-top: 8px; padding: 8px 10px; border: 1px solid var(--line);
  border-radius: 3px; background: var(--field); color: var(--text); font: inherit; font-size: .9rem;
  resize: vertical; }
textarea:focus-visible, button:focus-visible, summary:focus-visible { outline: 2px solid var(--link);
  outline-offset: 1px; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 10px; }
button { font: inherit; font-weight: 700; padding: 7px 16px; border-radius: 3px; cursor: pointer;
  border: 1px solid var(--text); background: var(--text); color: var(--bg); }
button.ghost { background: transparent; color: var(--muted); border-color: var(--line); font-weight: 400; }
#msg { font-size: .9rem; color: var(--muted); }
@media print {
  textarea, .actions, #feedback { display: none; }
  pre, .split > * { max-height: none; position: static; overflow: visible; }
}
</style>
</head>
<body>
<main>
<header>
  <div class="kind">@@KIND@@</div>
  <h1>@@TITLE@@</h1>
  @@SUBJECT@@
  <div class="meta">@@META@@</div>
  <ul class="members" aria-label="@@REVIEWERS_LABEL@@">@@MEMBERS@@</ul>
</header>
@@BODY@@
</main>
<script id="council-data" type="application/json">@@DATA@@</script>
<script>
(function () {
  var D = JSON.parse(document.getElementById('council-data').textContent);
  var boxes = Array.prototype.slice.call(document.querySelectorAll('textarea.comment'));
  var out = document.getElementById('fb-out'), msg = document.getElementById('msg');
  var saved = {};
  // Drafts survive a reload when the browser allows storage; the page works without it.
  try { saved = JSON.parse(localStorage.getItem(D.key) || '{}'); } catch (e) {}
  function openItem(el) { if (el && el.tagName === 'DETAILS') el.open = true; }
  boxes.forEach(function (b) {
    if (saved[b.dataset.id]) { b.value = saved[b.dataset.id]; openItem(b.closest('details')); }
    b.addEventListener('input', function () {
      saved[b.dataset.id] = b.value;
      try { localStorage.setItem(D.key, JSON.stringify(saved)); } catch (e) {}
    });
  });
  // A link from the overview table opens the item it points to.
  document.addEventListener('click', function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (a) openItem(document.getElementById(a.getAttribute('href').slice(1)));
  });
  if (location.hash.length > 1) openItem(document.getElementById(decodeURIComponent(location.hash.slice(1))));
  window.addEventListener('beforeprint', function () {
    Array.prototype.forEach.call(document.querySelectorAll('details.item'), openItem);
  });
  function build() {
    var lines = [];
    boxes.forEach(function (b) {
      var v = b.value.trim();
      if (!v) return;
      var head = b.dataset.id === 'overall' ? b.dataset.label : '[' + b.dataset.id + '] ' + b.dataset.label;
      lines.push('- ' + head + '\\n' + v.split('\\n').map(function (l) { return '  ' + l; }).join('\\n'));
    });
    return lines.length ? '## ' + D.title + '\\n\\n' + lines.join('\\n') + '\\n' : '';
  }
  document.getElementById('copy').addEventListener('click', function () {
    var text = build();
    if (!text) { msg.textContent = D.empty; out.hidden = true; return; }
    out.value = text; out.hidden = false;
    function fallback() {
      out.focus(); out.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) {}
      msg.textContent = ok ? D.copied : D.copyFailed;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { msg.textContent = D.copied; }, fallback);
    } else { fallback(); }
  });
  document.getElementById('clear').addEventListener('click', function () {
    boxes.forEach(function (b) { b.value = ''; });
    saved = {}; out.hidden = true; msg.textContent = '';
    try { localStorage.removeItem(D.key); } catch (e) {}
  });
})();
</script>
</body>
</html>
"""


def collect_raw(dirs):
    raw = []
    for d in dirs:
        for fname in RAW_FILES:
            p = Path(d) / fname
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if len(text) > RAW_LIMIT:
                text = text[:RAW_LIMIT] + f"\n\n[truncated; full text: {p}]"
            if text.strip():
                raw.append((f"{Path(d).name}/{fname}" if len(dirs) > 1 else fname, text))
    return raw


def main():
    ap = argparse.ArgumentParser(description="Render a council report.json as a self-contained HTML page.")
    ap.add_argument("--input", required=True, help="report.json written by Claude (schema: references/report.md)")
    ap.add_argument("--out", help="HTML file to write (default: report.html next to --input)")
    ap.add_argument("--lang", help="language of the page's headings and labels: "
                    + ", ".join(LABELS) + ", or any code covered by --labels (default: report.json 'lang', else en)")
    ap.add_argument("--labels", help="JSON file of label overrides, e.g. to add a language: {\"summary\": \"...\"}")
    ap.add_argument("--raw-dir", action="append", default=None,
                    help="council-ask.sh --out-dir whose raw answers to embed (repeatable, one per round; "
                         "default: the directory of --input)")
    ap.add_argument("--no-raw", action="store_true", help="leave raw agent outputs out of the page")
    ap.add_argument("--open", action="store_true", help="open the page in the default browser afterwards")
    args = ap.parse_args()

    src = Path(args.input)
    try:
        report = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"cannot read {src}: {e}")
    if not isinstance(report, dict):
        fail("report.json must be a JSON object")
    validate(report)

    lang = args.lang or report.get("lang") or "en"
    labels = dict(LABELS["en"])
    labels.update(LABELS.get(lang, {}))
    if args.labels:
        try:
            extra = json.loads(Path(args.labels).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            fail(f"cannot read --labels file: {e}")
        if not isinstance(extra, dict) or not all(isinstance(v, str) for v in extra.values()):
            fail("--labels file must be a JSON object of label key -> text")
        labels.update(extra)
    elif lang not in LABELS:
        fail(f"no built-in labels for --lang {lang} (built in: {', '.join(LABELS)}); "
             "pass --labels FILE with translations of the label keys")

    raw = [] if args.no_raw else collect_raw(args.raw_dir or [src.parent])
    out = Path(args.out) if args.out else src.with_name("report.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(report, labels, raw, lang), encoding="utf-8")
    print(f"report: {out.resolve()}")

    if args.open:
        for opener in ("wslview", "xdg-open", "open"):
            if shutil.which(opener):
                subprocess.Popen([opener, str(out.resolve())],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
        else:
            print("no browser opener found; open the file above by hand", file=sys.stderr)


if __name__ == "__main__":
    main()
