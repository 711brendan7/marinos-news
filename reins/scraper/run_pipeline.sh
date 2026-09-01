#!/bin/bash
# REINS パイプライン: 三浦スクレイパー → 足立区スクレイパー を順番に実行
# launchd から1本で呼ぶことで「時刻ずれ」なく巡回する。
# 仕入れスコアリングは廃止（2026-09-01）。スコアラー(../scorer)は呼ばない。
cd "$(dirname "$0")"

echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [1/2] 三浦スクレイパー開始（REINS→シート）"
HEADLESS=false venv/bin/python reins_scraper.py
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [1/2] 三浦スクレイパー終了 (exit=$?)"

# 足立区は独立系統（別シート・別フォルダ・「（足立区）」通知をLINEグループへ）。
# 三浦の後に順次実行してREINSログインの衝突を避ける。
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [2/2] 足立区スクレイパー開始"
./run_adachi.sh
echo "▶ $(date '+%Y-%m-%d %H:%M:%S') [2/2] 足立区スクレイパー終了 (exit=$?)"
