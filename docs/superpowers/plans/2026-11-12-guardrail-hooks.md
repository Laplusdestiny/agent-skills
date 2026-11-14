# Guardrail Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** APM プリミティブとして deny / ask / allow の3段階で判定する PreToolUse ガードレール hook を追加する。

**Architecture:** `.apm/hooks/guardrails.json` が `scripts/guard.py` を起動する。`guard.py` は Claude / Copilot の入力を
`Action` に正規化し、`guard_rules.py` のルールで判定して各ハーネスの形式で出力する。

**Tech Stack:** Python 3.8+（標準ライブラリのみ）、unittest、APM 0.35.x、GitHub Actions

**Spec:** `docs/superpowers/specs/2026-11-12-guardrail-hooks-design.md`

## Global Constraints

- Python 3.8+ 互換（`match` 文・`X | None` 型注釈禁止、`from __future__ import annotations` を使う）、標準ライブラリのみ。
- 判定の優先順位は deny > ask > allow > 該当なし。該当なしは stdout に何も出さない。
- 想定外の例外は stderr に警告を出して exit 0（fail-open）。
- Copilot 形式の入力では ask を deny に変換、allow は出力なし。
- `.apm/hooks/` 配下に JSON ファイルは `guardrails.json` 以外置かない（Copilot の hook ローダーが再帰スキャンするため）。

## Review Focus

- 秘密ファイル例外: `cat .env.example` / `Write .env.example` はブロックされないこと（Task 2 のテストに含める）。
- クォート内の文字列: `git commit -m "fix rm -rf / docs"` や `echo "a && rm -rf /"` は D1 にならないこと（Task 2）。
- クォート不整合: `echo "unterminated` で例外にならず、allow も返さないこと（Task 3）。
- `sudo rm -rf /` は ask ではなく deny（優先順位）になること（Task 2）。
- Windows パス区切り `C:\repo\.env` が D6 に該当すること（Task 2）。

---

### Task 1: 入力正規化・出力整形・エントリポイント

**Files:**
- Create: `.apm/hooks/scripts/guard.py`
- Create: `.apm/hooks/scripts/guard_rules.py`（この Task では `evaluate` の空実装のみ）
- Test: `tests/test_guard.py`

**Interfaces:**
- Produces（guard.py）:
  - `Action`（NamedTuple: `kind: str`（`"shell"` / `"write"`）, `value: str`）
  - `parse_input(payload: dict) -> Tuple[Optional[Action], str]` — 2要素目はハーネス `"claude"` / `"copilot"`
  - `format_output(decision: Optional[Decision], harness: str) -> Optional[dict]`
  - `main(stdin: TextIO, stdout: TextIO) -> int`
- Produces（guard_rules.py）:
  - `Decision`（NamedTuple: `decision: str`（`"deny"` / `"ask"` / `"allow"`）, `rule_id: str`, `reason: str`）
  - `evaluate(action: Action) -> Optional[Decision]`

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_guard.py` は `.apm/hooks/scripts` を `sys.path` に追加して import する。
  - `test_parse_claude_bash`: `{"tool_name":"Bash","tool_input":{"command":"ls"}}` → `(Action("shell","ls"), "claude")`
  - `test_parse_claude_write`: `Write`/`Edit`/`MultiEdit` の `file_path`、`NotebookEdit` の `notebook_path` → `Action("write", path)`
  - `test_parse_copilot_bash`: `{"toolName":"bash","toolArgs":"{\"command\":\"ls\"}"}` → `(Action("shell","ls"), "copilot")`
  - `test_parse_copilot_edit`: `toolName` が `edit` / `create`、`toolArgs` に `path` → `Action("write", path)`
  - `test_parse_other_tool`: `Read` / `Grep` → `(None, "claude")`
  - `test_format_claude`: deny → `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[guardrails D1] ..."}}`
  - `test_format_copilot_ask_becomes_deny`: ask → `{"permissionDecision":"deny","permissionDecisionReason":...}`（理由に "manually" を含む）
  - `test_format_copilot_allow_is_silent`: allow → `None`
  - `test_main_invalid_json`: 入力 `"not json"` → 戻り値 0、stdout 空
- [ ] **Step 2: 実行して失敗を確認** — `python3 -m unittest discover -s tests -v` → ImportError で FAIL
- [ ] **Step 3: 実装** — `guard.py` は `__file__` のディレクトリを `sys.path` に入れて `guard_rules` を import。理由文は `"[guardrails <id>] <reason>"` 形式。`main` 全体を `try/except Exception` で包み fail-open。
- [ ] **Step 4: 実行して成功を確認** — 同コマンドで全 PASS
- [ ] **Step 5: コミット** — `feat(hooks): add guardrail hook entrypoint with input normalization`

### Task 2: deny / ask ルール

**Files:**
- Modify: `.apm/hooks/scripts/guard_rules.py`
- Test: `tests/test_guard_rules.py`

**Interfaces:**
- Consumes: `Action`, `Decision`（Task 1）
- Produces:
  - `split_segments(command: str) -> Tuple[List[List[str]], bool]` — トークン列のセグメント一覧と、shlex が成功したかのフラグ
  - `strip_prefix(tokens: List[str]) -> List[str]` — 先頭の `sudo`/`env`/`nohup`/`time`/`command`/`exec`/`nice` とその直後のオプション・`VAR=val` を除去
  - `RULES: List[Rule]`（`Rule` NamedTuple: `id, decision, scope, pattern, reason`。`scope` は `"segment"` / `"command"` / `"path"`）

- [ ] **Step 1: 失敗するテストを書く** — `CASES = [(rule_id or None, kind, value), ...]` のテーブル駆動テスト `test_rule_table`。spec の deny/ask 表の各例を1件以上と、次の「該当しない」例を含める:
  - `rm -rf ./build`, `rm -rf node_modules` → None
  - `git commit -m "fix rm -rf / docs"` → None、`echo "a && rm -rf /"` → None
  - `git push -f origin main` → D2、`git push origin +main` → D2、`git push -f` → A2、`git push origin main` → A3、`git push origin feature/x` → None
  - `git restore --staged a.txt` → None、`git restore a.txt` → A1
  - `sudo rm -rf /` → D1、`sudo ls` → A5
  - `cat .env.example` → None、`cat .env` → D5、`cat ~/.ssh/id_rsa` → D5
  - write: `.env.example` → None、`C:\repo\.env` → D6、`/repo/.git/config` → D7、`/repo/apm.lock.yaml` → D8、`/repo/.claude/settings.json` → A6、`/repo/src/app.py` → None
  - `test_precedence`: `git status && rm -rf /` → D1
- [ ] **Step 2: 実行して失敗を確認** — `python3 -m unittest tests.test_guard_rules -v` → FAIL
- [ ] **Step 3: 実装** — `segment` ルールは `strip_prefix` 後のトークンを空白結合した文字列に、`command` ルールは生のコマンド文字列に、`path` ルールは `\` を `/` に置換したパスに `re.search` する。`evaluate` は RULES を走査し、最も強い decision（deny > ask）を返す。A5 の `sudo` は prefix 除去前のセグメントで判定する。
- [ ] **Step 4: 実行して成功を確認** — 全 PASS
- [ ] **Step 5: コミット** — `feat(hooks): add deny and ask guardrail rules`

### Task 3: allow 判定

**Files:**
- Modify: `.apm/hooks/scripts/guard_rules.py`
- Test: `tests/test_guard_rules.py`

**Interfaces:**
- Consumes: `split_segments`（Task 2）
- Produces: `is_allowed(command: str) -> bool`。`evaluate` は deny/ask が無く `is_allowed` が真なら `Decision("allow", "L", ...)` を返す（`rule_id` は該当カテゴリ `L1`〜`L3` のうち最初のセグメントのもの）

- [ ] **Step 1: 失敗するテストを書く** — `test_allow_table`:
  - allow: `git status`, `git -C sub log --oneline`, `git branch -a`, `ls -la && git diff`, `rg foo | head`, `find . -name '*.py'`, `gh pr view 12`, `cd sub && git status`
  - not allow: `git branch -D x`, `git push`, `find . -delete`, `find . -exec rm {} \;`, `echo $(whoami)`, `echo hi > out.txt`, `FOO=1 ls`, `npm test`, `echo "unterminated`, `gh pr merge 1`, `ls && npm install`
- [ ] **Step 2: 実行して失敗を確認**
- [ ] **Step 3: 実装** — 生コマンドに `$(`, `` ` ``, `<(`, `>(` があれば False。トークンに `>`/`>>`/`<`/`&>` 系があれば False。shlex 失敗時は False。各セグメントの先頭トークンでコマンド別の許可関数を引く。
- [ ] **Step 4: 実行して成功を確認**
- [ ] **Step 5: コミット** — `feat(hooks): auto-allow read-only commands`

### Task 4: hook 定義・CI・README

**Files:**
- Create: `.apm/hooks/guardrails.json`
- Create: `.github/workflows/test-hooks.yml`
- Modify: `README.md`
- Test: `tests/test_guard.py`（E2E 追加）

- [ ] **Step 1: E2E テストを書く** — `test_e2e_*`: `subprocess.run([sys.executable, GUARD], input=json)` で Claude 形式 `rm -rf /` → deny JSON、Copilot 形式 `git reset --hard` → deny JSON、Claude 形式 `git status` → allow JSON、`Read` → stdout 空。
- [ ] **Step 2: 実行して PASS を確認**（Task 1〜3 で実装済みのため）
- [ ] **Step 3: `guardrails.json` を作成** — フラットエントリ `{"type":"command","command":"python3 ./scripts/guard.py","bash":"python3 ./scripts/guard.py","timeout":10,"timeoutSec":10}` を `PreToolUse` に1件。
- [ ] **Step 4: APM 実機確認** — 一時ディレクトリにこのリポジトリを依存に持つ consumer を作り `apm install`。`.claude/settings.json` と `.github/hooks/agent-skills-guardrails.json` が生成され、配置済みスクリプトに Claude 形式 JSON を流して deny が返ること。
- [ ] **Step 5: CI と README** — workflow は `push` / `pull_request` で `actions/setup-python`（3.8 と 3.12 のマトリクス）→ `python -m unittest discover -s tests -v`。README に「ガードレール hooks」節（判定一覧の要約、ハーネス別挙動、ルール追加手順、制限事項）を追加し、ディレクトリ構成表に `.apm/hooks/` と `tests/` を追記。
- [ ] **Step 6: コミット** — `feat(hooks): register guardrail hook and add CI`
