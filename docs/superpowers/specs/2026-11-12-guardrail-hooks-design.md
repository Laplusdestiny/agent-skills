# Guardrail hooks 設計

- 日付: 2026-11-12
- ステータス: 承認済み（チャットでの合意内容を記録）

## 目的

agent-skills を `apm install` するすべてのプロジェクトで、コーディングエージェントに
「やってはいけないこと」をさせず、「やっていいこと」は確認なしで進められるようにする。
既存の `git-operations` スキルに散文で書かれている禁止事項（破壊的 git 操作、秘密情報の扱い）を、
PreToolUse hook として強制可能なルールに置き換える（harness-engineering の「Constraints」層）。

## スコープ

- 配布対象: APM プリミティブとして `.apm/hooks/` に置き、このパッケージを install した全プロジェクトに適用する。
- 対象ハーネス: `apm.yml` の targets（`claude`, `copilot`）。
- 対象外: テスト/ビルドコマンドの自動許可（任意コード実行になるため。必要ならプロジェクト側の
  `permissions` で許可する）。

## 判定ポリシー（3段階）

優先順位は **deny > ask > allow > 該当なし**。該当なしの場合 hook は何も出力せず、通常の権限フローに任せる。

### deny（常にブロック）

| ID | 対象 | 例 |
|---|---|---|
| D1 | ルート/ホーム/カレント/全体への `rm -rf` | `rm -rf /`, `rm -rf ~`, `rm -rf $HOME`, `rm -rf .`, `rm -rf *` |
| D2 | 保護ブランチ（main/master）への force push | `git push -f origin main`, `git push --force-with-lease origin master`, `git push origin +main` |
| D3 | git hook のスキップ | `git commit --no-verify`, `git commit -n`, `git push --no-verify` |
| D4 | ディスク/システム破壊 | `mkfs.*`, `dd ... of=/dev/...`, `> /dev/sd*`, `chmod -R 777 /`, fork bomb |
| D5 | 秘密ファイルの表示 | `cat/less/more/head/tail/bat .env`, `id_rsa`, `*.pem`, `*.key`（`.env.example` / `.env.sample` / `.env.template` は可） |
| D6 | 秘密ファイルへの書き込み（Edit/Write） | `.env*`（同上の例外あり）, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `.ssh/` 配下 |
| D7 | `.git/` 内部の直接編集（Edit/Write） | `.git/config`, `.git/hooks/*` |
| D8 | ロックファイルの手編集（Edit/Write） | `apm.lock.yaml`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `uv.lock`, `poetry.lock`, `Cargo.lock` |
| D9 | リポジトリ削除 | `gh repo delete` |

### ask（ユーザーに確認）

| ID | 対象 | 例 |
|---|---|---|
| A1 | 破壊的 git 操作 | `git reset --hard`, `git clean -f`, `git checkout -- <file>`, `git restore <file>`（`--staged` のみは除く）, `git branch -D`, `git push --delete`, `git push origin :branch` |
| A2 | 保護ブランチ以外への force push | `git push --force-with-lease origin feature/x` |
| A3 | main/master への直接 push | `git push origin main` |
| A4 | マージ/リリース/デプロイ | `gh pr merge`, `gh release create`, `npm publish`, `vercel --prod`, `vercel deploy --prod` |
| A5 | 権限昇格・リモートスクリプトのパイプ実行 | `sudo ...`, `curl ... \| sh`, `wget -O- ... \| bash` |
| A6 | ハーネス自身の編集（Edit/Write） | `.claude/settings.json`, `.claude/settings.local.json`, `.github/hooks/` 配下 |
| A7 | ファイル読み取りツールでの秘密ファイル参照（Read/Grep 等） | Claude `Read` / `Grep`、Copilot CLI `view` / `grep`、VS Code `read_file` で `.env*`（例外あり）, `*.pem`, `*.key`, `id_rsa` 等を対象にした場合 |

ブランチ判定（D2 / A3）はコマンド引数に `main` / `master` が refspec として明示された場合のみ行う
（hook 内で現在ブランチは調べない）。ブランチ未指定の force push（`git push -f`）は A2 として ask になる。

### allow（自動許可）

複合コマンドの**全セグメント**が allow に該当する場合のみ allow を返す。
`$(...)`、バッククォート、`>`/`>>` リダイレクト、`<(...)` を含むコマンドは allow しない。
先頭に環境変数代入（`FOO=bar cmd`）があるセグメントも allow しない。

| ID | 対象 |
|---|---|
| L1 | 読み取り専用 git: `status`, `diff`, `log`, `show`, `blame`, `rev-parse`, `ls-files`, `remote`（引数なし or `-v`）, `branch`（引数なし or `-a`/`-r`/`-v`/`-vv`/`--list`/`--show-current`）, `stash list`。`git -C <path>` 形式も可 |
| L2 | 読み取り専用シェル: `ls`, `pwd`, `cd`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`, `find`（`-delete`/`-exec`/`-execdir`/`-ok`/`-fprint*` なし）, `which`, `tree`, `file`, `stat`, `du`, `df`, `echo` |
| L3 | 読み取り専用 gh: `pr view/list/diff/checks/status`, `issue view/list`, `run view/list` |

`cat` 等が秘密ファイルを指す場合は D5 が先に適用されるため allow にならない。

## ハーネス別の挙動

| 判定 | Claude Code | Copilot（CLI / coding agent） |
|---|---|---|
| deny | `permissionDecision: "deny"` | `permissionDecision: "deny"` |
| ask | `permissionDecision: "ask"` | **deny に変換**（Copilot は ask を処理しないため安全側に倒す。理由文に「手動で実行して」と記載） |
| allow | `permissionDecision: "allow"` | 出力なし（Copilot は allow を処理しない） |
| 該当なし | 出力なし | 出力なし |

## アーキテクチャ

```
.apm/hooks/
  guardrails.json          # PreToolUse。command（Claude/VS Code）と bash（Copilot）を併記、timeout/timeoutSec
  scripts/
    guard.py               # エントリポイント: stdin → 正規化 → 判定 → 出力
    guard_rules.py         # ルール定義（データのみ）
tests/test_guard.py        # unittest
.github/workflows/test-hooks.yml
```

- `guardrails.json` はフラットエントリで書く。APM が Claude 向けに `matcher: "*"` のグループへ変換し、
  スクリプトを `.claude/hooks/<pkg>/scripts/`、Copilot 向けに `.github/hooks/scripts/<pkg>/scripts/` へ配置する
  （APM 0.35.1 で検証済み。Claude Code は余分な `bash` キーを無視することも実機で確認済み）。
- **入力正規化**: Claude 形式（`tool_name` / `tool_input`）と Copilot CLI 形式（`toolName` / `toolArgs` が JSON 文字列）を
  受け取り、`Action(kind="shell" | "write" | "read", value=...)` に変換する。
  - shell: `Bash`, `bash`, `shell`, `run_in_terminal` 等、入力に文字列 `command` を持つツール
  - write: `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `edit`, `create` 等、ツール名に edit/write/create/replace/insert を含み
    `file_path` / `path` / `filePath` / `notebook_path` を持つツール
  - read: `Read`, `Grep`, `view`, `grep`, `read_file`（大文字小文字を無視）で、同じパスキーを持つツール
  - それ以外は即座に終了（出力なし）。
- **コマンド分割**: `shlex`（`punctuation_chars=True`）でトークン化し、`&&`, `||`, `;`, `|`, `&`, 改行でセグメントに分割。
  クォート不整合で `shlex` が失敗した場合は空白分割にフォールバックし、allow は返さない。
  各セグメントは先頭の `sudo`, `env`, `nohup`, `time`, `command`, `exec`, `nice` とその直後のオプション/代入を除去してから照合する。
  D4 の fork bomb、A5 のパイプ実行のようにセグメントをまたぐパターンはコマンド全体に対して照合する。
- **ルール表現**: `guard_rules.py` に `Rule(id, decision, kind, pattern, reason, scope)` のリストとして定義する
  （`scope` は `segment` / `raw_segment` / `command` / `path` / `read_path`）。allow は別関数で判定する（コマンド名ごとの引数制約が必要なため）。
- **エラー処理**: 想定外の例外は stderr に警告を出して exit 0（fail-open）。ガードのバグで全ツールが止まることを避ける。
  これは正規表現ベースのバックストップであり、サンドボックスではない旨を README に明記する。
- **互換性**: Python 3.8+、標準ライブラリのみ。

## テスト

- `tests/test_guard.py`（unittest）:
  - ルールごとにブロックされる例・ブロックされない例のテーブル駆動テスト
  - allow の複合コマンド・危険な構文（`$(...)`, `>`）の扱い
  - `guard.py` を subprocess で起動し、Claude 形式 / Copilot 形式の JSON 入出力を検証する E2E テスト
  - 不正な JSON 入力で exit 0・出力なしになること
- CI: `.github/workflows/test-hooks.yml` で push / pull_request 時に `python -m unittest discover -s tests` を実行。

## ドキュメント

README に「ガードレール hooks」節を追加: 判定一覧、ハーネス別挙動、ルール追加手順、制限事項（バイパス可能性、fail-open、python3 依存）。
