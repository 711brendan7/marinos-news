#!/usr/bin/env python3
"""
realestate 手動トリガー監視（フラグ方式）

制御シート B1(リクエスト時刻ms) を launchd から30秒ごとにチェックし、
未処理のリクエストがあれば scraper.py を実行して B3(処理済み) と B2(状態) を更新する。
Mac が Google に問い合わせる方式なので、ポート開放・VPN不要。
"""
import fcntl
import os
import re
import subprocess
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

from google.oauth2.service_account import Credentials
import gspread

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
CRED = os.getenv("GOOGLE_CREDENTIALS", os.path.join(HERE, "credentials.json"))
PYTHON = os.path.join(HERE, "venv/bin/python")
SCRAPER = os.path.join(HERE, "scraper.py")
LOCK = "/tmp/realestate-trigger.lock"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]


def control_sheet():
    gc = gspread.authorize(Credentials.from_service_account_file(CRED, scopes=SCOPES))
    return gc.open_by_key(SPREADSHEET_ID).worksheet("制御")


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def scraper_running():
    r = subprocess.run(["pgrep", "-f", "scraper.py"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def main():
    # 多重起動防止: 前回の監視がまだ実行中(=巡回中)なら即終了
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return

    try:
        sh = control_sheet()
        requested = _int(sh.acell("B1").value)
        processed = _int(sh.acell("B3").value)
        if requested <= processed:
            return  # 新規リクエストなし

        # 定時実行(8:00/14:00)と重複しないようチェック
        if scraper_running():
            sh.update_acell("B2", "⏳ 既存の巡回が進行中。順番待ち…")
            return  # processed は更新せず次回ポーリングで再試行

        sh.update_acell("B2", "🏃 巡回中…（1〜3分）")
        result = subprocess.run(
            [PYTHON, SCRAPER], cwd=HERE,
            env={**os.environ, "ANTHROPIC_API_KEY": ""},  # 完全API不使用で実行
            capture_output=True, text=True,
        )
        out = result.stdout
        mnew = re.search(r"✅ (\d+) 件の新規物件を", out)
        mchg = re.search(r"💰 (\d+) 件の価格変更を", out)
        n = mnew.group(1) if mnew else "0"
        c = mchg.group(1) if mchg else "0"
        now = datetime.now().strftime("%H:%M")
        msg = f"✅ 完了 新規{n}件"
        if c != "0":
            msg += f" / 価格変更{c}件"
        msg += f"（{now}）"
        sh.update_acell("B3", str(requested))  # 処理済みマーク
        sh.update_acell("B2", msg)
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()


if __name__ == "__main__":
    main()
