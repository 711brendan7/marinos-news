#!/usr/bin/env python3
"""Brevo API で「1都3県」バッチを1日ぶんずつ自動送信する。

前提: make_lists.py で out/batches/batch_NN.csv を生成済み。
      .env に BREVO_API_KEY 等を設定済み(.env.example 参照)。

コマンド:
    python3 brevo_send.py setup          # フォルダ+バッチ別リスト作成+連絡先取込(一度だけ)
    python3 brevo_send.py schedule --live # 全バッチを連続日で予約送信(Brevoが自動送信/冪等)
    python3 brevo_send.py send-next --live# 次の未送信バッチを今すぐ送る(schedule未使用時)
    python3 brevo_send.py stats           # 各キャンペーンの送信/開封/バウンス
    python3 brevo_send.py report --live   # 日次レポート(地域内訳+実績)を REPORT_TO にメール
    python3 brevo_send.py daily --live    # report → send-next(launchd日次用/send-next運用時)

安全:
    --live を付けないと実際の作成/送信はせず、何をするかだけ表示(dry-run)。
    まず 'setup' → 少量の batch_01 で 'send-next --live' を試し、結果を stats で確認。
    問題なければ 'schedule --live' で残りを予約(既存は自動skip)。
    schedule で予約済みなら送信は Brevo が自動実行(Mac不要)。launchd は report 専用で運用。

依存: 標準ライブラリのみ(urllib)。pip 不要。
"""
import json, os, sys, glob, time, re, csv, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.brevo.com/v3"
JST = timezone(timedelta(hours=9))
STATE = os.path.join(HERE, "out", "state.json")


def load_env():
    # 独自パーサー: このスクリプトは pip 不要（標準ライブラリのみ）で launchd から
    # 単体実行できることを設計上の要件にしているため、python-dotenv には依存しない。
    # 他プロジェクト(note/reins/receipt/busshin等)がpython-dotenvを使うのとは意図的に違う。
    env = {}
    p = os.path.join(HERE, ".env")
    if not os.path.exists(p):
        sys.exit(".env がありません。.env.example をコピーして値を埋めてください。")
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    if not env.get("BREVO_API_KEY", "").startswith(("xkeysib-", "xsmtpsib-")):
        sys.exit("BREVO_API_KEY が未設定です。Brevo Settings → SMTP & API で作成してください。")
    return env


ENV = None
DRY = True


def api(method, path, payload=None, _retries=3):
    """Brevo REST 呼び出し。DRY のときは書き込み系(POST/PUT)を実行せず擬似応答。

    一時的なネットワークエラー・5xx・429(レート制限)は指数バックオフで自動リトライする。
    4xx(リクエスト自体が不正)は即座に諦めて詳細を出す。
    """
    url = API + path
    if DRY and method in ("POST", "PUT"):
        print(f"  [dry-run] {method} {path} {json.dumps(payload, ensure_ascii=False)[:120] if payload else ''}")
        return {"id": 0, "dryrun": True}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "api-key": ENV["BREVO_API_KEY"],
        "accept": "application/json",
        "content-type": "application/json",
    })
    last_err = None
    for attempt in range(1, _retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            if e.code == 429 or e.code >= 500:
                last_err = f"API error {e.code} {method} {path}: {detail}"
            else:
                raise SystemExit(f"API error {e.code} {method} {path}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = f"network error {method} {path}: {e}"
        if attempt < _retries:
            wait = 2 ** attempt
            print(f"  [retry {attempt}/{_retries}] {last_err} -> {wait}秒後に再試行")
            time.sleep(wait)
    raise SystemExit(f"{_retries}回リトライしても失敗: {last_err}")


def get_or_create_folder(name):
    res = api("GET", "/contacts/folders?limit=50&offset=0")
    for f in res.get("folders", []):
        if f["name"] == name:
            return f["id"]
    res = api("POST", "/contacts/folders", {"name": name})
    return res.get("id")


def get_list_by_name(name):
    offset = 0
    while True:
        res = api("GET", f"/contacts/lists?limit=50&offset={offset}")
        for l in res.get("lists", []):
            if l["name"] == name:
                return l["id"]
        if len(res.get("lists", [])) < 50:
            return None
        offset += 50


def get_or_create_list(name, folder_id):
    lid = get_list_by_name(name)
    if lid:
        return lid
    res = api("POST", "/contacts/lists", {"name": name, "folderId": folder_id})
    return res.get("id")


def import_csv(list_id, csv_path):
    body = open(csv_path, encoding="utf-8-sig").read()
    res = api("POST", "/contacts/import", {
        "listIds": [list_id],
        "fileBody": body,
        "updateExistingContacts": True,
        "emailBlacklist": False,
        "smsBlacklist": False,
    })
    return res


def build_html():
    txt = open(os.path.join(HERE, "email_body.txt"), encoding="utf-8").read().rstrip("\n")
    html_body = txt.replace("\n", "<br>\n")
    # Brevo はキャンペーンに配信停止リンクを自動付与するが、明示も入れておく
    unsub = '<p style="font-size:12px;color:#888;margin-top:24px">' \
            '配信停止をご希望の場合はこちら: <a href="{{ unsubscribe }}">配信停止</a></p>'
    return (
        '<div style="font-family:sans-serif;font-size:14px;line-height:1.7;color:#222;'
        'white-space:normal;max-width:640px">'
        f"{html_body}{unsub}</div>"
    )


def batch_files():
    d = os.path.join(HERE, ENV.get("BATCH_DIR", "out/batches"))
    return sorted(glob.glob(os.path.join(d, "batch_*.csv")))


def list_name_for(path):
    return "brendan_" + os.path.splitext(os.path.basename(path))[0]  # brendan_batch_01


def cmd_setup():
    folder = get_or_create_folder(ENV.get("LIST_FOLDER", "brendan-mail"))
    files = batch_files()
    if not files:
        sys.exit("out/batches/batch_*.csv がありません。先に make_lists.py を実行してください。")
    print(f"フォルダ id={folder} / バッチ {len(files)} 個を取込")
    for p in files:
        name = list_name_for(p)
        lid = get_or_create_list(name, folder)
        n = sum(1 for _ in open(p, encoding="utf-8-sig")) - 1
        print(f"  {name} (list id={lid}) ← {p} ({n}件)")
        import_csv(lid, p)
    print("setup 完了" + (" (dry-run)" if DRY else ""))


def cmd_schedule():
    subject = ENV["SUBJECT"]
    html = build_html()
    sender = {"name": ENV["SENDER_NAME"], "email": ENV["SENDER_EMAIL"]}
    reply_to = ENV["REPLY_TO"]
    start = datetime.strptime(ENV["START_DATE"], "%Y-%m-%d")
    hh, mm = map(int, ENV["SEND_TIME"].split(":"))
    files = batch_files()
    # 既存キャンペーン名を集めて重複予約を防ぐ(queuedはDELETE不可なので冪等性が重要)。
    existing = set()
    if not DRY:
        res = api("GET", "/emailCampaigns?type=classic&limit=100&offset=0")
        existing = {c.get("name") for c in (res.get("campaigns") or [])}
    for i, p in enumerate(files):
        name = list_name_for(p)
        camp_name = f"物件仕入れ {os.path.basename(p)}"
        when = datetime(start.year, start.month, start.day, hh, mm, tzinfo=JST) + timedelta(days=i)
        if camp_name in existing:
            print(f"  skip: {camp_name} は予約済み")
            continue
        lid = get_list_by_name(name)
        if not lid:
            sys.exit(f"リスト {name} が未作成です。先に setup を実行してください。")
        camp = {
            "name": camp_name,
            "subject": subject,
            "sender": sender,
            "replyTo": reply_to,
            "htmlContent": html,
            "recipients": {"listIds": [lid]},
            "scheduledAt": when.isoformat(),  # RFC3339(+09:00 コロン付き)
        }
        res = api("POST", "/emailCampaigns", camp)
        print(f"  予約: {name} → {when.isoformat()} (campaign id={res.get('id')})")
    print("schedule 完了" + (" (dry-run)" if DRY else ""))


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"next": 0}


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"), ensure_ascii=False)


def cmd_send_next():
    files = batch_files()
    st = load_state()
    i = st["next"]
    if i >= len(files):
        print("全バッチ送信済み。")
        return
    p = files[i]
    name = list_name_for(p)
    lid = get_list_by_name(name)
    if not lid:
        sys.exit(f"リスト {name} が未作成です。先に setup を実行してください。")
    camp = {
        "name": f"物件仕入れ {os.path.basename(p)}",
        "subject": ENV["SUBJECT"],
        "sender": {"name": ENV["SENDER_NAME"], "email": ENV["SENDER_EMAIL"]},
        "replyTo": ENV["REPLY_TO"],
        "htmlContent": build_html(),
        "recipients": {"listIds": [lid]},
    }
    res = api("POST", "/emailCampaigns", camp)
    cid = res.get("id")
    print(f"  作成: {name} (campaign id={cid})")
    if not DRY:
        api("POST", f"/emailCampaigns/{cid}/sendNow")
        st["next"] = i + 1
        save_state(st)
    print(f"send-next 完了: batch {i+1}/{len(files)}" + (" (dry-run)" if DRY else ""))


def cmd_stats():
    res = api("GET", "/emailCampaigns?type=classic&status=sent&limit=50&offset=0")
    for c in res.get("campaigns", []):
        s = _stats_of(c)
        print(f"  [{c.get('id')}] {c.get('name')}  送={s.get('sent',0)} 開封={s.get('uniqueViews',0)} "
              f"クリック={s.get('uniqueClicks',0)} バウンス={s.get('hardBounces',0)+s.get('softBounces',0)} "
              f"苦情={s.get('complaints',0)} 配信停止={s.get('unsubscriptions',0)}")


_PREF_SHORT = {"東京都": "東京", "神奈川県": "神奈川", "埼玉県": "埼玉", "千葉県": "千葉"}


def batch_region(name):
    """キャンペーン名(物件仕入れ batch_NN.csv)→対応バッチCSVの都道府県内訳を文字列で返す。"""
    m = re.search(r"batch_(\d+)\.csv", str(name))
    if not m:
        return "-"
    path = os.path.join(HERE, ENV.get("BATCH_DIR", "out/batches"), f"batch_{m.group(1)}.csv")
    if not os.path.exists(path):
        return "-"
    counts = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            p = (row.get("PREFECTURE") or "").strip()
            counts[p] = counts.get(p, 0) + 1
    order = ["東京都", "神奈川県", "埼玉県", "千葉県"]
    parts = [f"{_PREF_SHORT.get(p, p)}{counts[p]}" for p in order if counts.get(p)]
    for p in counts:  # 想定外の県があれば末尾に
        if p not in order and counts[p]:
            parts.append(f"{p}{counts[p]}")
    return " / ".join(parts) if parts else "-"


_STAT_KEYS = ("sent", "delivered", "uniqueViews", "uniqueClicks",
              "hardBounces", "softBounces", "complaints", "unsubscriptions")


def _stats_of(c):
    """統計を取得。globalStats が 0/空でも campaignStats(リスト別)を合算して埋める。
    無料プランでは globalStats が反映されず campaignStats のみ値を持つことがあるため。"""
    st = c.get("statistics", {}) or {}
    g = dict(st.get("globalStats", {}) or {})
    if not g.get("sent"):  # globalStats が空 → リスト別を合算
        agg = {k: 0 for k in _STAT_KEYS}
        for cs in st.get("campaignStats", []) or []:
            for k in _STAT_KEYS:
                agg[k] += cs.get(k, 0) or 0
        if agg["sent"]:
            return agg
    return g


def campaign_rows():
    """『物件仕入れ』各キャンペーンの統計。"""
    res = api("GET", "/emailCampaigns?type=classic&limit=100&offset=0")
    rows = []
    for c in res.get("campaigns", []):
        if not str(c.get("name", "")).startswith("物件仕入れ"):
            continue
        s = _stats_of(c)
        rows.append({
            "name": c.get("name"), "status": c.get("status"),
            "region": batch_region(c.get("name")),
            "sent": s.get("sent", 0), "delivered": s.get("delivered", 0),
            "opens": s.get("uniqueViews", 0), "clicks": s.get("uniqueClicks", 0),
            "bounce": s.get("hardBounces", 0) + s.get("softBounces", 0),
            "comp": s.get("complaints", 0), "unsub": s.get("unsubscriptions", 0),
        })
    rows.sort(key=lambda r: r["name"])
    return rows


def cmd_report():
    """配信結果の日次レポートを REPORT_TO に自動送信(Brevo transactional)。"""
    rows = campaign_rows()
    keys = ["sent", "delivered", "opens", "clicks", "bounce", "comp", "unsub"]
    tot = {k: sum(r[k] for r in rows) for k in keys}
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    subj = f"【物件仕入れ 配信レポート】{now}"
    if not rows:
        inner = "<p>まだ送信済みキャンペーンはありません。</p>"
    else:
        headers = ["キャンペーン", "地域(都道府県)", "状態", "送信", "開封", "クリック", "バウンス", "苦情", "配信停止"]
        th = "".join(f"<th style='padding:4px 8px;border:1px solid #ddd;background:#f5f5f5'>{h}</th>" for h in headers)
        trs = ""
        for r in rows:
            orate = f"{r['opens']/r['delivered']*100:.0f}%" if r["delivered"] else "-"
            cells = [r["name"], r["region"], r["status"], r["sent"], f"{r['opens']} ({orate})",
                     r["clicks"], r["bounce"], r["comp"], r["unsub"]]
            trs += "<tr>" + "".join(f"<td style='padding:4px 8px;border:1px solid #ddd'>{c}</td>" for c in cells) + "</tr>"
        torate = f"{tot['opens']/tot['delivered']*100:.0f}%" if tot["delivered"] else "-"
        inner = (f"<p><b>累計</b>: 送信 {tot['sent']} / 開封 {tot['opens']} ({torate}) / "
                 f"クリック {tot['clicks']} / バウンス {tot['bounce']} / 苦情 {tot['comp']} / 配信停止 {tot['unsub']}</p>"
                 f"<table style='border-collapse:collapse;font-size:13px'><tr>{th}</tr>{trs}</table>")
    html = f"<div style='font-family:sans-serif;color:#222'><h3>物件仕入れ 配信レポート</h3><p>{now}</p>{inner}" \
           f"<p style='color:#888;font-size:12px;margin-top:16px'>自動送信 / brendan-mailer</p></div>"
    to = ENV.get("REPORT_TO") or ENV["REPLY_TO"]
    api("POST", "/smtp/email", {
        "sender": {"name": ENV["SENDER_NAME"], "email": ENV["SENDER_EMAIL"]},
        "to": [{"email": to}], "subject": subj, "htmlContent": html,
    })
    print(f"report 送信 → {to}" + (" (dry-run)" if DRY else ""))


def _next_free_days(camps, count):
    """既存予約の最終日の翌日から count 個ぶんの連続送信日時(JST)を返す。"""
    hh, mm = map(int, ENV["SEND_TIME"].split(":"))
    latest = None
    for c in camps:
        sa = c.get("scheduledAt")
        if not sa:
            continue
        d = datetime.strptime(sa[:10], "%Y-%m-%d").date()
        if latest is None or d > latest:
            latest = d
    base = latest or datetime.now(JST).date()
    days = []
    for i in range(count):
        d = base + timedelta(days=i + 1)
        days.append(datetime(d.year, d.month, d.day, hh, mm, tzinfo=JST))
    return days


def cmd_auto_resend():
    """suspended で張り付いたバッチを検出し、残りを空き枠に自動で送り直し予約する。
    冪等: 同名の _resend が既にあればスキップ。resend 自体(batch_NN_resend)は対象外＝無限ループ防止。
    無料枠300/日を守るため他予約の翌空き日に1件ずつ入れる。"""
    res = api("GET", "/emailCampaigns?type=classic&limit=100&offset=0")
    camps = res.get("campaigns", []) or []
    existing = {c.get("name") for c in camps}
    stuck = []
    for c in camps:
        m = re.match(r"物件仕入れ batch_(\d+)\.csv$", str(c.get("name", "")))
        if m and c.get("status") == "suspended":
            resend_name = f"物件仕入れ batch_{m.group(1)}_resend"
            if resend_name not in existing:
                stuck.append((c, resend_name))
    if not stuck:
        print("auto-resend: 張り付き無し")
        return
    days = _next_free_days(camps, len(stuck))
    for (c, resend_name), when in zip(stuck, days):
        lid = (c.get("recipients", {}) or {}).get("lists", [None])[0]
        if not lid:
            print(f"  skip: {resend_name} リストID取得不可")
            continue
        payload = {
            "name": resend_name,
            "subject": ENV["SUBJECT"],
            "sender": {"name": ENV["SENDER_NAME"], "email": ENV["SENDER_EMAIL"]},
            "replyTo": ENV["REPLY_TO"],
            "htmlContent": build_html(),
            "recipients": {"listIds": [lid]},
            "scheduledAt": when.isoformat(),
        }
        if DRY:
            print(f"  [dry-run] {resend_name} → {when.isoformat()} (list {lid})")
        else:
            r = api("POST", "/emailCampaigns", payload)
            print(f"  作成: {resend_name} → {when.isoformat()} (list {lid}, id={r.get('id')})")
    print("auto-resend 完了" + (" (dry-run)" if DRY else ""))


def cmd_watch():
    """launchd 日次用: レポート送信 + 張り付き自動送り直し(auto-resend)。"""
    cmd_report()
    cmd_auto_resend()


def cmd_daily():
    """launchd 日次用: レポート送信 → 次バッチ送信。"""
    cmd_report()
    cmd_send_next()


def main():
    global ENV, DRY
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    DRY = "--live" not in sys.argv[2:]
    ENV = load_env()
    if DRY and cmd in ("setup", "schedule", "send-next", "report", "daily", "auto-resend", "watch"):
        print("*** dry-run(--live なし): 実際の作成/送信はしません ***")
    {"setup": cmd_setup, "schedule": cmd_schedule, "send-next": cmd_send_next,
     "stats": cmd_stats, "report": cmd_report, "daily": cmd_daily,
     "auto-resend": cmd_auto_resend, "watch": cmd_watch}.get(
        cmd, lambda: sys.exit(f"unknown: {cmd}"))()


if __name__ == "__main__":
    main()
