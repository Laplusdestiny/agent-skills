# agent-skills

[APM (Agent Package Manager)](https://github.com/microsoft/apm) で管理する、AIエージェント向けの agent / skills 定義リポジトリです。

## セットアップ

```bash
apm install
```

`apm.yml` の依存関係を解決し、`apm_modules/` に取得したパッケージを展開したうえで、各ターゲット（`.claude/`, `.agents/` など）にスキルをデプロイします。

依存関係を変更した場合は、必ず `apm install` を再実行してデプロイ内容をロックファイルと同期させてください。ドリフト（手動編集や再デプロイ漏れ）がないか確認したい場合は `apm audit` を使います。

## ディレクトリ構成

| パス | 役割 |
| --- | --- |
| `apm.yml` | プロジェクト定義。依存スキル、対象ターゲット、スクリプトを宣言する一次ソース |
| `apm.lock.yaml` | 依存解決結果のロックファイル（自動生成、手編集しない） |
| `.apm/skills/` | このリポジトリ自身が提供する自作スキルのソース |
| `.apm/hooks/` | 自作 hooks のソース（ガードレール。下記参照） |
| `tests/` | hooks のテスト（`python3 -m unittest discover -s tests`） |
| `apm_modules/` | 外部パッケージから取得した依存の実体（gitignore対象、`apm install` で再生成可能） |
| `.claude/`, `.agents/` | `apm install` がデプロイした、各エージェントターゲット向けの展開済みスキル（自動生成物。直接編集しない） |

## 自作スキル（`.apm/skills/`）

- **git-operations** — ブランチ作成・コミット（Conventional Commits）・PR作成・コンフリクト解消など、Git操作を安全に行うためのガイド
- **vercel-cli** — Vercel CLIを使ったデプロイ、ビルド/ランタイムログの確認、環境変数の同期を行うためのガイド
- **agent-council** — Claude Code を司令塔に、Codex CLI（`codex`）と Antigravity CLI（`agy`）を連携させるスキル。並列マルチレビュー・クロスレビュー・専用 git worktree での実装委任・設計相談（合議）・UI/デザインレビューをカバーし、結果は Claude が検証したうえで指摘ごとの合意表にまとめる。合議結果は言語を指定して HTML レポート（`council-report.py`）としても出力し、ユーザーの意見を受けて追加検討するラウンドを回せる（旧 `antigravity-collab` を統合）

外部依存スキル（`gh-cli`, `grill-me` など）は `apm.yml` / `apm.lock.yaml` で管理しているため、ここでは一覧化しません。最新の依存関係は `apm.yml` を参照してください。

## ガードレール hooks（`.apm/hooks/`）

`apm install` したプロジェクトに PreToolUse hook を配布し、エージェントのシェル実行・ファイル書き込み・秘密ファイルの読み取りを
**deny（ブロック）/ ask（ユーザー確認）/ allow（自動許可）** の3段階で判定します。優先順位は deny > ask > allow で、
どれにも該当しない操作は hook が何もせず通常の権限フローに任せます。設計の詳細は
[`docs/superpowers/specs/2026-11-12-guardrail-hooks-design.md`](docs/superpowers/specs/2026-11-12-guardrail-hooks-design.md) を参照してください。

| 判定 | 主な対象 |
| --- | --- |
| deny | `rm -rf /`・`~`・`.`・`*`、main/master への force push、`--no-verify`、`mkfs`/`dd of=/dev/...` などの破壊的コマンド、`cat .env` など秘密ファイルの表示、`.env`・秘密鍵・`.ssh/` への書き込み、`.git/` 内部やロックファイルの手編集、`gh repo delete` |
| ask | `git reset --hard`・`clean -f`・`checkout --`・`restore`・`branch -D`・リモートブランチ削除、その他の force push、main/master への直接 push、`gh pr merge`・`gh release create`・`npm publish`・`vercel --prod`、`sudo`、`curl ... \| sh`、`.claude/settings*.json`・`.github/hooks/` の編集、Read / Grep ツールでの秘密ファイル（`.env`・秘密鍵など）の読み取り |
| allow | 読み取り専用の `git`（status/diff/log/show など）、`ls`・`cat`・`grep`・`rg`・`find` などのシェルコマンド、`gh pr view/list` などの参照系 `gh`。複合コマンドは全セグメントが該当する場合のみ。`$(...)`・バッククォート・リダイレクトを含むものは対象外 |

`bash -c '...'` に渡されたスクリプトも同じルールで再帰的に判定します。

### ハーネス別の挙動

| 判定 | Claude Code | GitHub Copilot |
| --- | --- | --- |
| deny | ブロック | ブロック |
| ask | 確認ダイアログ | **ブロック**（Copilot は ask を処理しないため安全側に倒す。必要ならユーザーが手動で実行） |
| allow | 確認なしで実行 | 何もしない（通常フロー） |

### ルールを追加する

1. `.apm/hooks/scripts/guard_rules.py` に判定関数を書き、`RULES` に `Rule(id, decision, scope, check, reason)` を追加する
   （`scope` は `segment` / `raw_segment` / `command` / `path` / `read_path`。詳細はファイル冒頭の docstring）。
2. `tests/test_guard_rules.py` の `CASES` に、ブロックされる例とされない例を追加する。
3. `python3 -m unittest discover -s tests` が通ることを確認する（CI でも Python 3.8 / 3.12 で実行）。

### 制限事項

- 正規表現・トークン解析によるバックストップであり、サンドボックスではありません。変数展開・エイリアス・スクリプトファイル経由の実行などでは回避できます。
- hook 自体が想定外のエラーを起こした場合は fail-open（何も判定せず通常フロー）です。ガードのバグで全ツールが止まることを避けるためです。
- 実行には `python3`（3.8 以上）が必要です。
- Claude Code では APM の変換によりすべてのツール呼び出しで起動しますが、シェル実行・ファイル書き込み・ファイル読み取り以外は即座に終了します。

## 対応ターゲット

`apm.yml` では `claude` と `copilot` をターゲットとして宣言しています。現時点でスキルが実際にデプロイされているのは `claude`（`.claude/`）のみで、`copilot` 向けの出力（`.github/copilot-instructions.md` など）はまだ生成されていません（`apm targets` で状態を確認できます）。

## ライセンス

[MIT License](./LICENSE)
