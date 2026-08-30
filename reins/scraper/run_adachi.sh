#!/bin/bash
# 足立区の独立巡回。三浦とは別スプレッドシート・別Driveフォルダ・別通知（（足立区）表記）。
# 仕入れスコアは通さない（スコア無しの生「🏠 REINS新着」通知のみ）。
# 通知先は .env の LINE_TO_ADACHI（LINEグループID）。未設定なら自分（LINE_USER_ID）へフォールバック。
cd "$(dirname "$0")"

# .env から足立区の通知先（LINEグループID）だけを取り出す
LINE_TO_ADACHI=$(grep -E '^LINE_TO_ADACHI=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")

echo "▶ $(date '+%Y-%m-%d %H:%M:%S') 足立区スクレイパー開始（REINS→専用シート）"
REINS_CONDITION=足立区 \
REINS_CONDITIONS=足立 \
LINE_TO="$LINE_TO_ADACHI" \
HEADLESS=false \
venv/bin/python reins_scraper.py
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') 足立区スクレイパー終了 (exit=$?)"
