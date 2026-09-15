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
| `apm_modules/` | 外部パッケージから取得した依存の実体（gitignore対象、`apm install` で再生成可能） |
| `.claude/`, `.agents/` | `apm install` がデプロイした、各エージェントターゲット向けの展開済みスキル（自動生成物。直接編集しない） |

## 自作スキル（`.apm/skills/`）

- **git-operations** — ブランチ作成・コミット（Conventional Commits）・PR作成・コンフリクト解消など、Git操作を安全に行うためのガイド
- **vercel-cli** — Vercel CLIを使ったデプロイ、ビルド/ランタイムログの確認、環境変数の同期を行うためのガイド
- **antigravity-collab** — Antigravity CLI（`agy`）と連携するためのガイド。ユーザーの明示的な依頼時にセカンドオピニオンを求めるモードと、大規模コンテキスト解析・マルチモーダル読解・ブラウザUI検証・並列マルチエージェント分解などAntigravityが得意なタスクを委任するモードの両方をカバーする

外部依存スキル（`gh-cli`, `grill-me` など）は `apm.yml` / `apm.lock.yaml` で管理しているため、ここでは一覧化しません。最新の依存関係は `apm.yml` を参照してください。

## 対応ターゲット

`apm.yml` では `claude` と `copilot` をターゲットとして宣言しています。現時点でスキルが実際にデプロイされているのは `claude`（`.claude/`）のみで、`copilot` 向けの出力（`.github/copilot-instructions.md` など）はまだ生成されていません（`apm targets` で状態を確認できます）。

## ライセンス

[MIT License](./LICENSE)
