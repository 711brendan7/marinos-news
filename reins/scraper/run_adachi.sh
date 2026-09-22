#!/bin/bash
# 足立区の独立巡回。三浦とは別スプレッドシート・別Driveフォルダ・別通知（（足立区）表記）。
# 仕入れスコアは通さない（スコア無しの生「🏠 REINS新着（足立区）」通知のみ）。
# 挙動（下の env で制御）:
#   - REINS_SPREADSHEET_URL: 専用シート固定＝作り直さない（新規0で再通知しない・PWA merge先と一致）
#   - REINS_DOWNLOAD_NEW_ONLY=1: 既知物件は図面DLをスキップ（毎回全件巡回しない）
#   - REINS_NOTIFY_ONLY_NEW=1: 新規0件のときは通知しない（新着があるときだけ）
#   - REINS_WALK_MAX_MIN=10: 駅徒歩10分超と確定した物件はLINE通知から除外（徒歩不明は通知＝安全側。シートは全件記録）
#   - REINS_PRIORITY_STATIONS_ONLY=1: 優先駅（◎ = ADACHI_PRIORITY_STATIONS）以外の駅はLINE通知から除外（駅不明は通知＝安全側。徒歩フィルタと併用。シートは全件記録）
#   - REINS_TSUBO_MAX=220: 坪単価220万円超と確定した土地・戸建はLINE通知から除外。戸建は「価格÷土地面積」で評価（REINS表示の坪単価は使わない）／土地はREINS表示値。坪単価不明は通知＝安全側。区分/アパートは対象外。シートは全件記録
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
REINS_WALK_MAX_MIN=10 \
REINS_PRIORITY_STATIONS_ONLY=1 \
REINS_TSUBO_MAX=220 \
LINE_TO="$LINE_TO_ADACHI" \
HEADLESS=false \
venv/bin/python reins_scraper.py
# $? は直前のコマンドの分を先に控える（echo 内の $(date) で上書きされるため）
RC=$?
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') 足立区スクレイパー終了 (exit=$RC)"
