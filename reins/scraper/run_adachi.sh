#!/bin/bash
# 足立区の独立巡回。三浦とは別スプレッドシート・別Driveフォルダ・別通知（（足立区）表記）。
# 仕入れスコアは通さない（スコア無しの生「🏠 REINS新着（足立区）」通知のみ）。
# 挙動（下の env で制御）:
#   - REINS_SPREADSHEET_URL: 専用シート固定＝作り直さない（新規0で再通知しない・PWA merge先と一致）
#   - REINS_DOWNLOAD_NEW_ONLY=1: 既知物件は図面DLをスキップ（毎回全件巡回しない）
#   - REINS_NOTIFY_ONLY_NEW=1: 新規0件のときは通知しない（新着があるときだけ）
#   - LINE_TO: 通知先を .env の LINE_TO_ADACHI（LINEグループID）に。未設定なら自分にフォールバック
cd "$(dirname "$0")"

# .env から足立区の通知先（LINEグループID）だけを取り出す
LINE_TO_ADACHI=$(grep -E '^LINE_TO_ADACHI=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")

# 足立区の専用スプレッドシートを固定（巡回ごとに作り直さない＝新規のみ通知・merge先も不変）。
# .env の REINS_SPREADSHEET_URL_ADACHI があればそれを使う（無ければキャッシュに従う）。
PIN_URL=$(grep -E '^REINS_SPREADSHEET_URL_ADACHI=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")

echo "▶ $(date '+%Y-%m-%d %H:%M:%S') 足立区スクレイパー開始（REINS→専用シート）"
REINS_CONDITION=足立区 \
REINS_CONDITIONS=足立 \
REINS_SPREADSHEET_URL="$PIN_URL" \
REINS_DOWNLOAD_NEW_ONLY=1 \
REINS_NOTIFY_ONLY_NEW=1 \
LINE_TO="$LINE_TO_ADACHI" \
HEADLESS=false \
venv/bin/python reins_scraper.py
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') 足立区スクレイパー終了 (exit=$?)"
