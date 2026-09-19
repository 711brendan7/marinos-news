#!/bin/bash
# REINS 三浦（秋谷含む）だけを手動で1回巡回する。
#
# 毎日の自動巡回は launchd (com.reins.scraper) → run_pipeline.sh が
# 「三浦 → 足立区」の順で回している。このスクリプトは足立区を回さず
# 三浦だけを手動で流したいときに使う。
#
# HEADLESS は設定しないこと（既定の false = 画面ありで動く）。
# REINS のログイン画面は reCAPTCHA Enterprise 付きの SPA なので、
# HEADLESS=true にするとログインフォームが描画されず
# 「wait_for_selector("input[type='text']") が 30 秒でタイムアウト」して
# 必ず失敗する。2026-09-19 にこれで失敗を確認済み。
cd "$(dirname "$0")"
venv/bin/python reins_scraper.py
