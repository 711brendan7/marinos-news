# note 収益化パイプライン

ブランド「無職から大家」（urlname: musyoku_ooya）の note 記事を、ネタ収集→下書き生成→
投稿→スキ周りまで一気通貫で支援するスクリプト群。API課金ではなく `claude -p` / `codex exec`
などログイン済みCLIの定額枠を使う方針（[../.claude memory: feedback_prefer_flat_rate_over_metered_api]）。

## 何から読むか

まず [style_guide.md](style_guide.md) を読む。ペルソナ・文体・タイトルの型・著作権ルール・
「人生哲学・信条」の更新手順がここに集約されている。実績の数字は [portfolio.md](portfolio.md)
で必ず確認してから記事に書く（二重記事・数字ブレ防止の実績台帳）。

## パイプライン（通常の実行順）

1. `collect_sources.py` — Google News RSS・はてなブックマークからネタ元を収集
2. `research.py` — ジャンルごとの人気記事を収集し収益性を比較
3. `draft_generator.py` — style_guide.md に沿って下書きを生成（Claude Code CLI）
4. `generate_image.py` — 見出し画像を生成（Codex CLI）
5. `publish_helper.py` — 半自動投稿（既定）。`--auto` で完全自動。■行は貼り付け時に見出しへ自動変換
6. `scheduled_publish.py` — 指定日時に1本公開（note予約投稿はプレミアム限定のため代替）

## 公開後のメンテナンス

- `fix_publish.py body` — 公開済み本文の差し替え
- `migrate_titles.py` — 既存記事のタイトルだけ新スタイルへ一括差し替え
- `strip_closing.py` — 末尾の定型（次回予告・お礼等）だけを削除
- `retire_merged.py` / `delete_dupes.py` — 統合・重複記事の削除（取り返しがつかない操作）
- `analyze.py` — 売れている有料noteの型（価格帯・タイトル特徴）を分析

## スキ周り自動化

`engage.py`（スキル `note-engage`）。本命ニッチの実務発信者にスキ＋返し。自動フォローは廃止済み。
`run_engage.command` をダブルクリックするか CLI から実行。

## サブディレクトリ

- `rakuyoko/` — 「ラクヨコ×Claude」型の副業プレイブック展開（[project_note_rakuyoko]）
- `output/` — 生成済み記事の下書き置き場

## 運用上の注意

- `.env` に note の認証情報等（コミットしない・`.gitignore`済み）
- `*.log` / `scratch_*.json` は使い捨ての実行ログ・中間データ
- `publish_helper.py` のログイン維持プロファイル `.note_profile/` は絶対にコミットしない
