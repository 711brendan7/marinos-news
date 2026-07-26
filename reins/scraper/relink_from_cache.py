#!/usr/bin/env python3
"""古い行の図面/フォルダ・リンク復旧ツール（cache.json からの再リンク）。

背景:
  2026年7月上旬に Drive リンク化が入る前（〜6月取得）の古い行は、
  スプレッドシートの「図面/詳細」「フォルダ」列に HYPERLINK 式ではなく
  「図面」「フォルダ」等のラベル文字だけが入っている。PWA(docs/reins.html)は
  その生文字をリンクにできず「ボタンを押しても図面が開けない/ボタンが出ない」。
  再取得しても直らない（スクレイパーは差分追記で既送信の物件番号をスキップする）。

  ただし図面ファイル自体は Drive の共有フォルダにアップ済みで、各物件の driveUrl は
  cache.json（キー: <条件>_<物件番号> の driveUrl）に残っている。→ ここから復旧する。

方式（コード再デプロイ不要・データのみ）:
  既存デプロイ済み GAS の 2 アクションだけを使う。
    1) deleteRowByReinsNo で古い行を削除（存在しない番号なら removed:0 で無害）
    2) appendToSheet で再追記 → GAS 側 applyRichTextLinks_ が HYPERLINK 式をセット
  安全策: 物件番号が複数シートに跨る行（例 477000002754 の ¥0 異常行）は触らない。

使い方:
  venv の python で実行（requests / リダイレクト対応が要る）。
    reins/scraper/venv/bin/python relink_from_cache.py analyze          # 対象を集計（変更なし）
    reins/scraper/venv/bin/python relink_from_cache.py run              # 全対象を復旧
    reins/scraper/venv/bin/python relink_from_cache.py run アパート      # 種別を限定
"""
import csv
import json
import os
import sys
from collections import defaultdict, Counter

import requests

GAS_URL = ("https://script.google.com/macros/s/"
           "AKfycbwg5gIdluJCKhxg5Ac37ojhD1RxblEidHziJUIo2vWPTMWdlzlxEkCeaE-CydbCHInz-g/exec")
SID = "1zah79pR7wlv_jGjCIhBWgCQEDoBmIXHHoT58SqTCrcE"
CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache.json")


def post(payload, tries=4):
    last = None
    for attempt in range(tries):
        try:
            s = requests.Session()
            s.max_redirects = 5
            r = s.post(GAS_URL, json=payload, timeout=120, allow_redirects=True)
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, r.text[:300]
        except requests.RequestException as e:
            last = e
            import time
            time.sleep(2 * (attempt + 1))
    return 0, f"request failed after {tries} tries: {last}"


def fetch_csv():
    r = requests.get(GAS_URL, params={"csv": "1"}, timeout=60, allow_redirects=True)
    r.raise_for_status()
    return list(csv.reader(r.text.splitlines()))


def strip_num(x):
    return (x or "").replace(",", "").strip()


def load_cache_index():
    """物件番号 -> {driveUrl, fileType, cond, fetchedAt, folderUrl} を返す。"""
    cache = json.load(open(CACHE_FILE, encoding="utf-8"))
    folders = {k[len("_folder_"):]: v.get("url", "")
               for k, v in cache.items() if k.startswith("_folder_") and isinstance(v, dict)}
    byno = {}
    for k, v in cache.items():
        if k.startswith("_") or "_" not in k or not isinstance(v, dict):
            continue
        if not v.get("driveUrl"):
            continue
        cond, no = k.split("_", 1)
        byno[no] = {
            "driveUrl": v["driveUrl"],
            "fileType": v.get("fileType", "ファイル"),
            "cond": cond,
            "fetchedAt": v.get("fetchedAt", ""),
            "folderUrl": folders.get(cond, ""),
            "kenpei": v.get("kenpei", ""),
            "yoseki": v.get("yoseki", ""),
            "buildingArea": v.get("buildingArea", ""),
            "shogo": v.get("shogo", ""),
        }
    return byno


def build_prop(row, col, cinfo):
    def c(name):
        return col(row, name)
    return {
        "reinsNo": c("物件番号"),
        "torihiki": c("取引態様"),
        "torihikiStatus": c("取引状況"),
        "propertyType": c("物件種目"),
        "price": strip_num(c("価格(万円)")),
        "yoto": c("用途地域"),
        "kenpei": c("建ぺい率") or cinfo["kenpei"],
        "yoseki": c("容積率") or cinfo["yoseki"],
        "landArea": strip_num(c("土地面積(㎡)")),
        "buildingArea": strip_num(c("建物面積(㎡)")) or cinfo["buildingArea"],
        "sqmPrice": strip_num(c("㎡単価(万円)")),
        "tsuboPrice": strip_num(c("坪単価(万円)")),
        "setsuDoStatus": c("接道状況"),
        "setsuDo1": c("接道１"),
        "address": c("所在地"),
        "line": c("路線"),
        "station": c("駅"),
        "walkMinutes": strip_num(c("徒歩(分)")),
        "bus": c("バス"),
        "shogo": c("商号") or cinfo["shogo"],
        "phone": c("電話番号"),
        "fetchedAt": cinfo["fetchedAt"] or c("取得日時"),
        "driveUrl": cinfo["driveUrl"],
        "fileType": cinfo["fileType"],
        "folderUrl": cinfo["folderUrl"],
    }


def dedup(props):
    """物件番号で重複排除（元シートの重複行を1件に集約）。"""
    seen, out = set(), []
    for p in props:
        if p["reinsNo"] in seen:
            continue
        seen.add(p["reinsNo"])
        out.append(p)
    return out


def relink_by_type(by_type):
    """種別ごとに「各物件番号を削除 → 再追記」。削除は冪等なので再実行安全。"""
    for ptype, props in by_type.items():
        props = dedup(props)
        print(f"\n=== {ptype}: {len(props)}件 ===")
        for p in props:
            sc, res = post({"action": "deleteRowByReinsNo", "spreadsheetId": SID, "reinsNo": p["reinsNo"]})
            if sc != 200:
                print(f"  delete {p['reinsNo']} -> {sc} {res}")
        sc, res = post({"action": "appendToSheet", "spreadsheetId": SID, "properties": props})
        print(f"  append {len(props)}件 -> {sc} {res}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    only_type = sys.argv[2] if len(sys.argv) > 2 else None

    # restore: 中断リカバリ。バックアップJSONを正本に全対象を作り直す（消失行も復元）。
    if mode == "restore":
        dump = os.path.join(os.path.dirname(__file__), "relink_targets_backup.json")
        targets = json.load(open(dump, encoding="utf-8"))
        if only_type:
            targets = [p for p in targets if p["propertyType"] == only_type]
        by_type = defaultdict(list)
        for p in targets:
            by_type[p["propertyType"]].append(p)
        print(f"restore: {sum(len(v) for v in by_type.values())}件 種別={ {k: len(v) for k, v in by_type.items()} }")
        relink_by_type(by_type)
        return

    byno = load_cache_index()
    rows = fetch_csv()
    h = rows[0]
    idx = {name: i for i, name in enumerate(h)}

    def col(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else ""

    # dedupe: 同一シート内の同一物件番号の重複行を1行に整理（リンクは保持）。
    if mode == "dedupe":
        seen = defaultdict(list)
        for r in rows[1:]:
            seen[(col(r, "物件種目"), col(r, "物件番号"))].append(r)
        by_type = defaultdict(list)
        for (ptype, no), rs in seen.items():
            if len(rs) < 2:
                continue
            r = rs[0]
            ci = byno.get(no)
            if ci is None:
                # cache に無い（既にリンク済みの行）→ CSVのURLをそのまま採用
                draw, fold = col(r, "図面/詳細"), col(r, "フォルダ")
                if not draw.startswith("http") and not fold.startswith("http"):
                    print(f"  skip {ptype} {no}: URL不明で整理不可"); continue
                ci = {"driveUrl": draw if draw.startswith("http") else "",
                      "fileType": "ファイル", "cond": "", "fetchedAt": "",
                      "folderUrl": fold if fold.startswith("http") else "",
                      "kenpei": "", "yoseki": "", "buildingArea": "", "shogo": ""}
            by_type[ptype].append(build_prop(r, col, ci))
        n = sum(len(v) for v in by_type.values())
        print(f"重複整理対象: {n}件 {{{', '.join(f'{k}:{len(v)}' for k,v in by_type.items())}}}")
        if only_type == "run":
            relink_by_type(by_type)
        else:
            print("（確認のみ。実行するには 'dedupe run'）")
        return

    sheets_of = defaultdict(set)
    for r in rows[1:]:
        sheets_of[col(r, "物件番号")].add(col(r, "物件種目"))

    targets, skipped_multi, no_cache = [], [], Counter()
    for r in rows[1:]:
        no = col(r, "物件番号")
        draw, fold = col(r, "図面/詳細"), col(r, "フォルダ")
        broken = (not draw.startswith("http")) or (not fold.startswith("http"))
        if not broken:
            continue
        if only_type and col(r, "物件種目") != only_type:
            continue
        if no not in byno:
            no_cache[col(r, "物件種目")] += 1
            continue
        if len(sheets_of[no]) > 1:
            skipped_multi.append(no)
            continue
        targets.append(build_prop(r, col, byno[no]))

    print(f"復旧対象: {len(targets)} 件  種別内訳: {dict(Counter(p['propertyType'] for p in targets))}")
    print(f"複数シート跨ぎでスキップ: {len(skipped_multi)} 件 {skipped_multi[:8]}")
    print(f"cacheにdriveUrl無し（復旧不可）: {dict(no_cache)}")

    if mode == "analyze":
        return
    if mode != "run":
        print(f"unknown mode: {mode}")
        return
    if not targets:
        print("対象なし。終了。")
        return

    # 削除前に対象データをダンプ（append失敗時の再投入用の保険）
    dump = os.path.join(os.path.dirname(__file__), "relink_targets_backup.json")
    json.dump(targets, open(dump, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"バックアップ: {dump}")

    # 種別ごとに「削除 → 再追記」。1種別ずつ完結させ、失敗時の影響とやり直しを局所化。
    by_type = defaultdict(list)
    for p in targets:
        by_type[p["propertyType"]].append(p)
    relink_by_type(by_type)


if __name__ == "__main__":
    main()
