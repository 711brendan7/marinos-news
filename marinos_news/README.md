# 横浜F・マリノス ニュースアプリ

横浜F・マリノスの関連ニュース・YouTube動画をRSS/YouTube Data APIから収集し、
Streamlitアプリで一覧表示する。

## ファイル構成

- `app.py` — Streamlit本体（画面表示）
- `news_fetcher.py` — RSSソース一覧（`RSS_SOURCES`）とニュース取得処理。
  ソース追加はスキル `add-rss-source` から行う
- `youtube_fetcher.py` — YouTube Data API 経由で関連動画を取得
- `static/` — アプリの静的アセット

## 起動・診断

- 起動: スキル `marinos-run`
- 動作がおかしい時の診断: スキル `marinos-debug`

## 注意

- `.streamlit/secrets.toml` にAPIキー等（コミットしない・gitignore済み）
- `venv/` は仮想環境（コミットしない・gitignore済み。誤って `git status` に
  untrackedとして出た場合は `.gitignore` の反映漏れを疑う）
