#!/usr/bin/env python3
"""
REINS 手動巡回トリガー監視（GAS制御シート・フラグ方式）

スマホPWAの「今すぐ巡回」が GAS の制御シート B1(リクエスト時刻) を更新する。
本スクリプトを launchd から20秒ごとに実行し、未処理のリクエストがあれば
run_pipeline.sh（スクレイパー→スコアラー→LINE）を実行して結果を GAS に書き戻す。
Mac が Google に問い合わせる方式なので、ポート開放・VPN・混在コンテンツの問題がない。
（旧 trigger_server.py の HTTP:8765 方式を置き換える。HTTPS PWA からは呼べないため）
"""
import fcntl
import os
import re
import subprocess
import warnings

warnings.filterwarnings("ignore")

import requests

HERE = os.path.dirname(os.path.abspath(__file__))

# .env から GAS_URL を読む（無ければ既定 = PWA と同じデプロイURL）
DEFAULT_GAS = ("https://script.google.com/macros/s/"
               "AKfycbwg5gIdluJCKhxg5Ac37ojhD1RxblEidHziJUIo2vWPTMWdlzlxEkCeaE-CydbCHInz-g/exec")


def load_env(key, default=""):
    env = os.path.join(HERE, ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8"):
            line = line.strip()
            if line.startswith(key + "="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    return default


GAS_URL = load_env("GAS_URL", DEFAULT_GAS)
DONE_TOKEN = load_env("REINS_SCRAPE_DONE_TOKEN")  # Secrets.gs の SCRAPE_DONE_TOKEN と一致させる
READ_TOKEN = load_env("REINS_READ_TOKEN")  # Code.gs の READ_TOKEN と一致させる
PIPELINE = os.path.join(HERE, "run_pipeline.sh")
LOCK = "/tmp/reins-trigger.lock"


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def status():
    r = requests.get(GAS_URL, params={"action": "scrapeStatus",
                                      "token": READ_TOKEN}, timeout=30)
    return r.json()


def mark(phase, result=""):
    requests.get(GAS_URL, params={
        "action": "markScrape", "token": DONE_TOKEN,
        "phase": phase, "result": result,
    }, timeout=30)


def pipeline_running():
    r = subprocess.run(["pgrep", "-f", "reins_scraper.py"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def summarize(out):
    total = re.findall(r"合計\s*(\d+)\s*件", out)
    newp = re.search(r"(?:新着|新規)\s*(\d+)\s*件", out)
    parts = []
    if newp:
        parts.append(f"新着{newp.group(1)}件")
    if total:
        parts.append(f"全{total[-1]}件")
    return " / ".join(parts) if parts else "完了"


def main():
    # 多重起動防止: 前回の監視（＝巡回中）がまだ実行中なら即終了
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return

    try:
        st = status()
        if _int(st.get("requested")) <= _int(st.get("processed")):
            return  # 新規リクエストなし

        # 定時実行と重複しないよう確認
        if pipeline_running():
            return  # processed は更新せず次回ポーリングで再試行

        mark("start")
        result = subprocess.run(
            ["/bin/bash", PIPELINE], cwd=HERE,
            env={**os.environ, "HEADLESS": "false", "PATH": "/usr/local/bin:/usr/bin:/bin"},
            capture_output=True, text=True,
        )
        mark("done", summarize(result.stdout))
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()


if __name__ == "__main__":
    main()
