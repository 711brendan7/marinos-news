# 物件スクレイパー & ビューアPWA

不動産会社ホームページを巡回して物件情報を収集し、スマホで見られるPWAとして公開する一式。
API課金は使わず、会社別パーサー方式（サイト構造決め打ち）で物件詳細を抽出する。

## パイプライン

1. `scraper.py` — Google スプレッドシートの会社URLリストを読み込み、各社サイトを巡回して
   物件情報を出力シートに追記する
2. `parsers.py` — 会社別パーサー（対応5社）。各社は「物件詳細ページURLの発見」だけを実装し、
   共通の `parse_detail()` で価格/所在地/面積/間取りを抽出する。サイト改装時は該当社の
   discovery 関数だけ直せばよい
3. `viewer.py` / `viewer.html` — スプレッドシートの物件データをプロキシ経由でPWAに表示
   （公開URL・GAS URL・トークンは project_realestate_viewer メモリ参照）
4. `trigger_watch.py` — 制御シートB1を launchd から30秒ごとにポーリングし、手動リクエストが
   あれば `scraper.py` を実行してB2/B3を更新する（ポート開放・VPN不要のフラグ方式）

## 周辺ツール

- `places_agents.py` — Google Maps Places API (New) で指定地域の不動産会社を集め、
  会社リストの仕込みに使う（スキル `places-agents`）
- `gas/` — Google Apps Script側の実装

## 注意

- `test_anthropic.py` / `test_gemini.py` はAPI疎通確認用の手動スクリプトであり、
  pytestのユニットテストではない（`test_*` 名だがCI等での自動収集は想定していない）
- `.env` にAPIキー・スプレッドシートID等（コミットしない・gitignore済み）
- `credentials.json`（サービスアカウント）もgitignore済み
