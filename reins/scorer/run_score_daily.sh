#!/bin/bash
# 毎日「今日の買い候補」を自動レポート
# GAS の CSV エンドポイント(?csv=1)から最新シートを取得 → スコアリング → HTML
# launchd/cron から呼べば毎朝自動実行できる（既存の reins 出力は無改造）。
cd "$(dirname "$0")"

GAS_URL="https://script.google.com/macros/s/AKfycbwg5gIdluJCKhxg5Ac37ojhD1RxblEidHziJUIo2vWPTMWdlzlxEkCeaE-CydbCHInz-g/exec"
# Code.gs の READ_TOKEN と一致させる（../scraper/.env の REINS_READ_TOKEN から読む）
READ_TOKEN=$(grep -E '^REINS_READ_TOKEN=' ../scraper/.env 2>/dev/null | cut -d= -f2- | tr -d "\"'")
MIN_SCORE="${1:-60}"

echo "▶ $(date '+%Y-%m-%d %H:%M') 最新シートを取得..."
curl -sL "${GAS_URL}?csv=1&token=${READ_TOKEN}" -o reins_live.csv -w "  取得: HTTP %{http_code} / %{size_download}bytes\n"

# 取得失敗(HTMLが返る)なら中断
if head -1 reins_live.csv | grep -q "物件番号"; then
  # 端末から手動実行時のみブラウザを開く（launchd等の自動実行では開かない）
  OPEN=""; [ -t 1 ] && OPEN="--open"
  python3 run_score.py reins_live.csv --min-score "$MIN_SCORE" $OPEN --line --only-new
else
  echo "⚠️ CSV取得に失敗（認証切れ/デプロイ未反映の可能性）。reins_live.csv を確認。"
  exit 1
fi
