#!/bin/bash
# REINS パイプライン: 三浦スクレイパー → スコアラー → 足立区スクレイパー を順番に実行
# launchd から1本で呼ぶことで「時刻ずれ」なく、スクレイプ完了後すぐ採点＆通知する。
cd "$(dirname "$0")"

echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [1/3] スクレイパー開始（REINS→シート）"
HEADLESS=false venv/bin/python reins_scraper.py
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [1/3] スクレイパー終了 (exit=$?)"

echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [2/3] スコアラー開始（シート→採点→新着LINE）"
../scorer/run_score_daily.sh 0
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [2/3] スコアラー終了 (exit=$?)"

# 足立区は独立系統（別シート・別フォルダ・スコア無し「（足立区）」通知をLINEグループへ）。
# 三浦の後に順次実行してREINSログインの衝突を避ける。
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [3/3] 足立区スクレイパー開始"
./run_adachi.sh
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [3/3] 足立区スクレイパー終了 (exit=$?)"
