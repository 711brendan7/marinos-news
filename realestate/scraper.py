#!/usr/bin/env python3
"""
不動産会社ホームページ巡回スクレイパー
Google スプレッドシートから会社URLリストを読み込み、
各サイトから物件情報を取得して出力シートに追記する。
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import gspread
import httpx
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

import parsers

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    WebPushException = Exception

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID", "")
INPUT_SHEET      = os.getenv("INPUT_SHEET", "会社リスト")
OUTPUT_SHEET     = os.getenv("OUTPUT_SHEET", "物件情報")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS", os.path.join(os.path.dirname(__file__), "credentials.json"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# LINE通知（reins/scraper/.env と同じキーを共有。未設定なら通知は送らない）
# 宛先は本人（LINE_USER_ID）固定。物件ウォッチの新着は自分だけに届けたいので、
# reins 側のようなグループ宛（LINE_TO）は意図的に見ない。
LINE_CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID       = os.getenv("LINE_USER_ID", "")
LINE_TARGET        = LINE_USER_ID


def send_line_notify(message):
    if not LINE_CHANNEL_TOKEN or not LINE_TARGET:
        print("ℹ️  LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID 未設定 → LINE通知はスキップ")
        return
    try:
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "to": LINE_TARGET,
                "messages": [{"type": "text", "text": message}],
            },
            timeout=30,
        )
        # 200以外を黙って捨てると「通知が来ない」原因が追えないので本文を出す
        if r.status_code != 200:
            print(f"⚠️  LINE push 失敗 {r.status_code}: {r.text[:300]}")
        else:
            print("📱 LINE通知送信完了")
    except Exception as e:
        print(f"⚠️  LINE通知エラー: {e}")


# PWA(docs/watch/) アプリアイコンのバッジ表示用（Web Push）。
# VAPID鍵は reins と共用（同じ Mac から送るので身元を分ける意味がない）。
GAS_URL      = os.getenv("GAS_URL", "")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "")
VAPID_PRIVATE_KEY_PATH = os.getenv(
    "VAPID_PRIVATE_KEY_FILE",
    os.path.join(os.path.dirname(__file__), "..", "reins", "scraper", "vapid_private.pem"))
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "")


def send_web_push(new_count):
    """新着件数をアプリアイコンのバッジに反映するため、登録済みの全端末へ Web Push を送る。
    LINE通知とは独立。GAS未設定/鍵未生成なら黙って何もしない。"""
    if webpush is None or new_count <= 0 or not GAS_URL or not SECRET_TOKEN:
        return
    if not os.path.exists(VAPID_PRIVATE_KEY_PATH):
        return
    try:
        res = requests.get(GAS_URL, params={"token": SECRET_TOKEN,
                                            "action": "pushSubscriptions"}, timeout=15)
        subs = res.json()
    except Exception as e:
        print(f"⚠️  Push購読者取得エラー: {e}")
        return
    if not isinstance(subs, list) or not subs:
        return

    payload = json.dumps({
        "title": "物件ウォッチ",
        "body": f"新着 {new_count}件",
        "count": new_count,
    })
    sent, expired = 0, 0
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY_PATH,
                vapid_claims={"sub": VAPID_SUBJECT},
                timeout=10,
            )
            sent += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):  # 購読が失効（アプリ削除・通知拒否など）→ GAS側の登録も消す
                expired += 1
                try:
                    requests.post(GAS_URL, json={"token": SECRET_TOKEN,
                                                 "action": "pushUnsubscribe",
                                                 "endpoint": sub.get("endpoint", "")}, timeout=10)
                except Exception:
                    pass
            else:
                print(f"⚠️  Push送信エラー: {e}")
    print(f"🔔 バッジPush送信完了（{sent}件" + (f"・失効{expired}件を解除" if expired else "") + "）")


def format_new_property_message(props):
    lines = [f"🏠 新着物件 {len(props)}件"]
    for p in props[:20]:
        price = p.get("price", "") or "価格不明"
        title = p.get("title", "") or p.get("address", "") or "(タイトル不明)"
        # 物件ページURLが取れなかったときも、掲載元の一覧ページに飛べるようにする
        link = p.get("url", "") or (f"（一覧）{p['source_url']}" if p.get("source_url") else "")
        lines.append(f"\n■ {p.get('company_name', '')}\n{title}\n{price}\n{link}")
    if len(props) > 20:
        lines.append(f"\n…他 {len(props) - 20} 件")
    return "\n".join(lines)

OUTPUT_HEADERS = ["取得日時", "会社名", "物件名・タイトル", "価格・賃料", "所在地", "面積・間取り", "物件URL", "会社URL", "価格変更"]
CONTROL_SHEET = "制御"     # 手動トリガー・最終巡回日時
CHANGE_SHEET = "価格変更"  # 価格変更の履歴ログ
CHANGE_HEADERS = ["変更日時", "会社名", "物件名・タイトル", "所在地", "旧価格", "新価格", "物件URL"]

PRICE_COL = 4   # D列（1-indexed）: 価格・賃料
CHANGE_COL = 9  # I列（1-indexed）: 価格変更

SHEETS_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.5",
}


# ── Google Sheets ─────────────────────────────────────────────

def get_sheets_client():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SHEETS_SCOPES)
    return gspread.authorize(creds)


def read_company_list(gc):
    ss = gc.open_by_key(SPREADSHEET_ID)
    sheet = ss.worksheet(INPUT_SHEET)
    all_values = sheet.get_all_values()
    # ヘッダー行（「会社名」列を含む行）を探す
    header_row = next((i for i, row in enumerate(all_values) if row and row[0] == "会社名"), 0)
    header = all_values[header_row] if header_row < len(all_values) else []
    # 列名から位置を特定（空ヘッダーの余分な列があっても影響を受けない）
    try:
        name_idx = header.index("会社名")
        url_idx  = header.index("URL")
    except ValueError:
        return []
    companies = []
    for row in all_values[header_row + 1:]:
        name = (row[name_idx] if len(row) > name_idx else "").strip()
        url  = (row[url_idx]  if len(row) > url_idx  else "").strip()
        if name and url and url.startswith("http"):
            companies.append((name, url))
    return companies


def ensure_output_headers(gc):
    ss = gc.open_by_key(SPREADSHEET_ID)
    sheet = ss.worksheet(OUTPUT_SHEET)
    first_row = sheet.row_values(1)
    if not first_row or first_row[0] != "取得日時":
        sheet.insert_row(OUTPUT_HEADERS, index=1)
    elif len(first_row) < len(OUTPUT_HEADERS):
        # 既存シートに不足列（価格変更）だけ追加（データは壊さない）
        sheet.update_cell(1, len(OUTPUT_HEADERS), OUTPUT_HEADERS[-1])


def wait_for_network(max_wait=180, host="sheets.googleapis.com"):
    """名前解決できるまで待つ。復帰しなければ False。"""
    import socket
    for i in range(0, max_wait, 10):
        try:
            socket.getaddrinfo(host, 443)
            if i:
                print(f"🌐 ネットワーク復帰を確認（{i}秒待機）")
            return True
        except socket.gaierror:
            if not i:
                print(f"🌐 ネットワーク未接続。最大{max_wait}秒待ちます…")
            time.sleep(10)
    return False


def record_last_run(gc, new_count, changed_count, failed_count=0):
    """最終巡回日時と結果を制御シートに記録（新着ゼロでも巡回した事実を残す）。"""
    ss = gc.open_by_key(SPREADSHEET_ID)
    try:
        sh = ss.worksheet(CONTROL_SHEET)
    except gspread.WorksheetNotFound:
        sh = ss.add_worksheet(title=CONTROL_SHEET, rows=10, cols=2)
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    summary = f"新規{new_count}件 / 価格変更{changed_count}件"
    # 取得できなかった件数も残す。「本当に新着ゼロ」と「取れていない」を区別するため。
    if failed_count:
        summary += f" ⚠️取得失敗{failed_count}件"
    sh.update(values=[["最終巡回日時", now], ["最終巡回結果", summary]],
              range_name="A4:B5", value_input_option="USER_ENTERED")


def get_change_log_sheet(gc):
    ss = gc.open_by_key(SPREADSHEET_ID)
    try:
        return ss.worksheet(CHANGE_SHEET)
    except gspread.WorksheetNotFound:
        sh = ss.add_worksheet(title=CHANGE_SHEET, rows=1000, cols=len(CHANGE_HEADERS))
        sh.append_row(CHANGE_HEADERS, value_input_option="USER_ENTERED")
        return sh


def get_existing_properties(gc):
    """物件URL → {row: 行番号(1-indexed), price: 記録済み価格} の辞書を返す。"""
    ss = gc.open_by_key(SPREADSHEET_ID)
    sheet = ss.worksheet(OUTPUT_SHEET)
    data = sheet.get_all_values()
    result = {}
    for i, row in enumerate(data[1:], start=2):  # 2行目以降（1-indexed行番号）
        url = row[6].strip() if len(row) > 6 else ""
        price = row[3].strip() if len(row) > 3 else ""
        if not url:
            # URLを取れなかった行（AI抽出）は scrape_company の dedup_key と同じ
            # 「タイトル__所在地」で登録する。登録しないと同じ物件が毎回新着扱いになり
            # リンク無しのLINE通知が巡回のたびに繰り返される。
            title = row[2].strip() if len(row) > 2 else ""
            address = row[4].strip() if len(row) > 4 else ""
            if title or address:
                result.setdefault(f"{title}__{address}", {"row": i, "price": price})
            continue
        result[url] = {"row": i, "price": price}
    return result


def append_properties(gc, properties):
    ss = gc.open_by_key(SPREADSHEET_ID)
    sheet = ss.worksheet(OUTPUT_SHEET)
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    rows = [
        [
            now,
            p.get("company_name", ""),
            p.get("title", ""),
            p.get("price", ""),
            p.get("address", ""),
            p.get("area_layout", ""),
            p.get("url", ""),
            p.get("source_url", ""),
            "",  # 価格変更（新規は空）
        ]
        for p in properties
    ]
    if rows:
        sheet.insert_rows(rows, row=2, value_input_option="USER_ENTERED")


def apply_price_changes(gc, changes):
    """価格変更を本体シートに反映（価格更新＋価格変更列）し、履歴シートに追記する。"""
    if not changes:
        return
    ss = gc.open_by_key(SPREADSHEET_ID)
    sheet = ss.worksheet(OUTPUT_SHEET)
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    # c["row"] は巡回開始時点の行番号。その後 append_properties が
    # insert_rows(row=2) で新規をヘッダー直後に差し込むため、新規N件ぶん
    # 全体がズレる。古い行番号で書くと無関係な物件を上書きしてしまうので、
    # 書き込む直前にURLで引き直す。
    data = sheet.get_all_values()
    row_by_url = {}
    for i, r in enumerate(data[1:], start=2):
        u = r[6].strip() if len(r) > 6 else ""
        if u and u not in row_by_url:
            row_by_url[u] = i
    for c in changes:
        row = row_by_url.get(str(c.get("url", "")).strip())
        if not row:
            print(f"    ⚠️  価格変更の対象行が見つからずスキップ: {c.get('url', '')}")
            continue
        arrow = "↓値下げ" if _price_num(c["price"]) < _price_num(c["old_price"]) else "↑値上げ"
        sheet.update_cell(row, PRICE_COL, c["price"])
        sheet.update_cell(row, CHANGE_COL,
                          f"{arrow} {c['old_price']}→{c['price']}（{now}）")
    log = get_change_log_sheet(gc)
    log.insert_rows(
        [[now, c.get("company_name", ""), c.get("title", ""), c.get("address", ""),
          c["old_price"], c["price"], c.get("url", "")] for c in changes],
        row=2, value_input_option="USER_ENTERED",
    )


def _price_num(s):
    """「2,800万円」「1億2,000万円」を万円単位の数値に。比較用（失敗時0）。"""
    s = str(s or "").replace(",", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)億(?:(\d+))?万?", s)
    if m:
        return int(float(m.group(1)) * 10000) + (int(m.group(2)) if m.group(2) else 0)
    m = re.search(r"(\d+(?:\.\d+)?)万", s)
    return int(float(m.group(1))) if m else 0


# ── Web スクレイピング ─────────────────────────────────────────

# 取得に失敗した回数。「本当に新着ゼロ」と「そもそも取れていない」を
# 巡回結果から区別するために数える（ネットワーク不通の検知用）。
FETCH_FAILURES = 0

# 巡回対象のエリア。検索条件つきのURLでも、サイト側が「おすすめ」「新着」として
# 全国の物件を同じページに載せることがあり（smtrc.jp）、そのまま取り込むと
# 名古屋・福岡などの無関係な物件がLINE通知に混ざる。
TARGET_AREAS = [a.strip() for a in
                os.getenv("REALESTATE_AREAS", "三浦市,横須賀市,逗子市,葉山町").split(",")
                if a.strip()]


def in_target_area(prop):
    """対象エリアの物件か。判定できないときは True（取りこぼさない側に倒す）。"""
    text = f"{prop.get('address', '')} {prop.get('title', '')}"
    if any(a in text for a in TARGET_AREAS):
        return True
    # 「市」「区」が読み取れて対象外なら除外。「町」は判定に使わない。
    # 地元業者は「神奈川県南下浦町金田」のように市名を省く（三浦市南下浦町）ため、
    # 町で判定すると対象物件まで捨ててしまう。
    return not re.search(r"[^\s都道府県]{2,8}?[市区]", text)


async def fetch_html(url, timeout=20, count_failure=True):
    # count_failure=False は Playwright へのフォールバックがある呼び出し用。
    # そこで数えると、実際には取得できた分まで「取得失敗」に計上されてしまう。
    global FETCH_FAILURES
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=HTTP_HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        # macOS同梱Pythonの LibreSSL 2.8.3 では smtrc.jp のTLSに対応できず
        # ハンドシェイクに失敗する（curlやブラウザでは通る）。TLS由来の失敗だけ
        # Playwright で引き直す。他の失敗まで回すと待ち時間が伸びるので限定する。
        if "SSL" in str(e).upper():
            html = await fetch_html_playwright(url, count_failure=False)
            if html:
                return html
        if count_failure:
            FETCH_FAILURES += 1
        print(f"    ⚠️  fetch失敗 {url}: {e}")
        return None


async def fetch_html_playwright(url, timeout=20000, count_failure=True):
    """JavaScriptが必要なサイト向け: PlaywrightでレンダリングしてからHTMLを取得する。"""
    global FETCH_FAILURES
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=HTTP_HEADERS["User-Agent"])
            # networkidle だけを待つと、広告や計測タグが鳴り続けるサイト（smtrc.jp 等）で
            # 必ずタイムアウトする。まず DOM の構築を待ち、その後 networkidle は
            # 短く待って諦める（JS描画が要るサイトもここで間に合う）。
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        if count_failure:
            FETCH_FAILURES += 1
        print(f"    ⚠️  Playwright取得失敗 {url}: {e}")
        return None


def clean_html(html, max_chars=6000):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)[:max_chars]

    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        label = a.get_text(strip=True)
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        if href in seen:
            continue
        if not label:
            label = href.split("/")[-1] or href  # URLのファイル名をラベルに使用
        links.append({"text": label[:40], "href": href})
        seen.add(href)
        if len(links) >= 60:
            break

    return text, links


# ── Anthropic API による解析 ──────────────────────────────────

_anthropic_client: Optional[anthropic.Anthropic] = None

def claude_generate(prompt):
    msg = _anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def find_listing_pages(company_name, base_url, page_text, links):
    """ホームページから物件一覧ページのURLを特定する。"""
    links_text = "\n".join(f"- {l['text']}: {l['href']}" for l in links)
    prompt = f"""不動産会社「{company_name}」のホームページ（{base_url}）を分析してください。

ページテキスト（抜粋）:
{page_text[:2000]}

ページ内のリンク一覧:
{links_text}

物件一覧ページや売買・賃貸物件の検索結果ページへのリンクを最大3件、絶対URLで返してください。
相対URLの場合はベースURL ({base_url}) を使って絶対URLに変換してください。

JSON配列のみを返してください（例）: ["https://example.com/bukken/", "https://example.com/sale/"]
物件一覧ページが見つからない場合は空配列: []
"""
    raw = claude_generate(prompt)
    match = re.search(r'\[.*?\]', raw, re.DOTALL)
    if not match:
        return []
    try:
        urls = json.loads(match.group())
        result = []
        for u in urls:
            if isinstance(u, str) and u.startswith("http"):
                result.append(u)
            elif isinstance(u, str):
                result.append(urljoin(base_url, u))
        return result[:3]
    except json.JSONDecodeError:
        return []


_RENTAL_KEYWORDS = ["月額", "/月", "円/月", "万円/月", "賃料", "家賃", "賃貸"]

def _is_rental(price: str) -> bool:
    return any(kw in price for kw in _RENTAL_KEYWORDS)


def extract_properties_from_page(company_name, page_url, page_text, links):
    """ページテキストから売買物件情報を抽出する（賃貸除外）。"""
    links_text = "\n".join(f"- {l['text']}: {l['href']}" for l in links) if links else "（リンクなし）"
    prompt = f"""以下は不動産会社「{company_name}」のウェブページ（{page_url}）から取得したテキストです。

【ページテキスト】
{page_text}

【ページ内リンク一覧】
{links_text}

このページに掲載されている**売買物件のみ**を抽出してください。
賃貸物件（月額・月払い・賃料・家賃・/月 などの表記）は必ず除外してください。

以下のJSON配列形式のみを返してください:
[
  {{
    "title": "物件名・タイトル",
    "price": "販売価格（例: 2,800万円、5,500万円）",
    "address": "所在地・住所",
    "area_layout": "面積・間取り（例: 85.5㎡ / 3LDK）",
    "url": "物件詳細ページの絶対URL（上記【ページ内リンク一覧】から物件タイトルに対応するhrefを探す。相対URLはベースURL {page_url} で絶対URLに変換。見つからない場合は空文字列）"
  }}
]

注意:
- 賃貸・月額・家賃・賃料の物件は絶対に含めない
- 売買物件（数千万円・億円単位の価格）のみ対象
- 物件URLは必ず【ページ内リンク一覧】のhrefから探して設定する
- 会社案内・サービス説明などの非物件情報は除く
- 物件が見つからない場合は空配列 [] を返す
"""
    raw = claude_generate(prompt)
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group())
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if _is_rental(item.get("price", "")):
                continue
            url = item.get("url", "").strip()
            if url and not url.startswith("http"):
                url = urljoin(page_url, url)
                item["url"] = url
            if item.get("title") or item.get("address"):
                result.append(item)
        return result
    except json.JSONDecodeError:
        return []


# ── メインスクレイピングロジック ──────────────────────────────

async def fetch_with_fallback(url):
    """httpxで取得し、リンクが少なければPlaywrightにフォールバック。"""
    html = await fetch_html(url, count_failure=False)
    if html:
        _, links = clean_html(html)
        if len(links) >= 3:
            return html
        print(f"    ⚡ JSレンダリングが必要と判断 → Playwright使用")
    html = await fetch_html_playwright(url)
    return html


async def scrape_company_parser(company_name, homepage_url, existing, discover):
    """会社別パーサーで抽出（API不使用）。新規と価格変更を検知する。"""
    print(f"  🔍 {company_name}（パーサー / API不使用）: {homepage_url}")
    items = await discover(homepage_url, fetch_html)
    new_props, changed_props = [], []
    seen_in_run = set()
    for it in items:
        url = it.get("url", "").strip()
        if not url or url in seen_in_run:
            continue
        seen_in_run.add(url)
        # 現在の物件データを取得（価格変更検知のため既存もチェック）
        if "address" in it or "price" in it:
            prop = {
                "title": it.get("title", ""),
                "price": it.get("price", ""),
                "address": it.get("address", ""),
                "area_layout": it.get("area_layout", ""),
                "url": url,
            }
            if not (prop["title"] or prop["address"]):
                continue
        else:
            html = await fetch_html(url)
            if not html:
                continue
            prop = parsers.parse_detail(html, url, it)
            if not prop:
                continue
            await asyncio.sleep(0.3)
        prop["company_name"] = company_name
        prop["source_url"] = homepage_url

        if url not in existing:
            new_props.append(prop)
            existing[url] = {"row": None, "price": prop["price"]}
        else:
            old = existing[url]["price"]
            new_price = prop["price"]
            if new_price and old and new_price != old:
                changed_props.append({**prop, "old_price": old, "row": existing[url]["row"]})
                existing[url]["price"] = new_price  # 同一実行内での二重検知を防ぐ
    print(f"    ✅ 新規 {len(new_props)} 件 / 💰 価格変更 {len(changed_props)} 件")
    return new_props, changed_props


async def scrape_company(company_name, homepage_url, existing):
    # 会社別パーサーがあれば優先（API不使用）
    if company_name in parsers.PARSERS:
        return await scrape_company_parser(
            company_name, homepage_url, existing, parsers.PARSERS[company_name]
        )

    # パーサー未対応の会社は Claude API にフォールバック（キーがある場合のみ）
    if _anthropic_client is None:
        print(f"  ⏭️  {company_name}: パーサー未対応・APIキー無しのためスキップ")
        return [], []

    print(f"  🔍 {company_name}（AI / API使用）: {homepage_url}")

    html = await fetch_with_fallback(homepage_url)
    if not html:
        return [], []

    page_text, links = clean_html(html)

    listing_urls = find_listing_pages(company_name, homepage_url, page_text, links)

    pages_to_check = [homepage_url] + listing_urls
    all_properties = []

    for page_url in pages_to_check:
        if page_url != homepage_url:
            html = await fetch_with_fallback(page_url)
            if not html:
                continue
            page_text, links = clean_html(html)

        props = extract_properties_from_page(company_name, page_url, page_text, links)
        all_properties.extend(props)
        await asyncio.sleep(1)

    new_props = []
    seen_in_run = set()
    for p in all_properties:
        prop_url = p.get("url", "").strip()
        dedup_key = prop_url if prop_url else f"{p.get('title','')}__{p.get('address','')}"
        if dedup_key and dedup_key not in existing and dedup_key not in seen_in_run:
            p["company_name"] = company_name
            p["source_url"] = homepage_url
            new_props.append(p)
            seen_in_run.add(dedup_key)
            if prop_url:
                existing[prop_url] = {"row": None, "price": p.get("price", "")}

    print(f"    ✅ {len(new_props)} 件の新規物件")
    return new_props, []


# ── エントリポイント ──────────────────────────────────────────

async def main():
    global _anthropic_client
    missing = []
    if not SPREADSHEET_ID:
        missing.append("SPREADSHEET_ID")
    if not os.path.exists(CREDENTIALS_FILE):
        missing.append(f"credentials.json（{CREDENTIALS_FILE}）")
    if missing:
        print(f"❌ 設定が不足しています: {', '.join(missing)}")
        print("  → realestate/.env を確認してください")
        sys.exit(1)

    # Anthropic API はパーサー未対応会社のフォールバック用（任意）
    if ANTHROPIC_API_KEY and anthropic is not None:
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    else:
        _anthropic_client = None
        print("ℹ️  ANTHROPIC_API_KEY 未設定 → パーサー対応会社のみ処理します（API不使用）")

    print("🏠 不動産会社ホームページ巡回スクレイパー 開始")
    print(f"   スプレッドシートID: {SPREADSHEET_ID}")

    # スリープ復帰直後など、ネットワーク確立前に launchd が起動することがある。
    # そのまま進むと全サイトの取得に失敗して「新規0件」と誤記録するので、先に待つ。
    if not wait_for_network():
        print("❌ ネットワークに接続できないため巡回を中止します（新規0件として記録しない）")
        sys.exit(1)

    gc = get_sheets_client()
    ensure_output_headers(gc)

    companies = read_company_list(gc)
    if not companies:
        print(f"⚠️  '{INPUT_SHEET}' シートに会社データがありません")
        print("   A列: 会社名、B列: URL の形式で入力してください")
        sys.exit(0)
    print(f"📋 {len(companies)} 社を巡回します\n")

    existing = get_existing_properties(gc)
    print(f"📊 既存登録物件数: {len(existing)} 件\n")

    all_new_props, all_changed = [], []
    for company_name, url in companies:
        try:
            new, changed = await scrape_company(company_name, url, existing)
            kept = [p for p in new if in_target_area(p)]
            if len(kept) != len(new):
                print(f"    🗺  対象エリア外を除外: {len(new) - len(kept)}件")
            all_new_props.extend(kept)
            all_changed.extend([c for c in changed if in_target_area(c)])
        except Exception as e:
            print(f"    ⚠️  {company_name} でエラー（スキップ）: {e}")
        await asyncio.sleep(2)

    print(f"\n{'─'*40}")
    if all_new_props:
        # 追記が失敗したら通知しない（シート未記録のまま通知すると、次回も同じ物件を
        # 新着として検知して二重通知になる）。ここで落とさず巡回記録まで進める。
        try:
            append_properties(gc, all_new_props)
        except Exception as e:
            print(f"⚠️  シート追記に失敗（LINE通知も見送り・次回再検知）: {e}")
        else:
            print(f"✅ {len(all_new_props)} 件の新規物件を '{OUTPUT_SHEET}' シートに追記しました")
            for i in range(0, len(all_new_props), 20):
                send_line_notify(format_new_property_message(all_new_props[i:i + 20]))
            send_web_push(len(all_new_props))
    else:
        print("📭 新規物件はありませんでした")
    if all_changed:
        apply_price_changes(gc, all_changed)
        print(f"💰 {len(all_changed)} 件の価格変更を検知・更新しました")
        for c in all_changed:
            print(f"    {c.get('company_name','')} {c.get('address','')[:16]} {c['old_price']}→{c['price']}")

    try:
        record_last_run(gc, len(all_new_props), len(all_changed), FETCH_FAILURES)
    except Exception as e:
        print(f"⚠️  最終巡回日時の記録に失敗: {e}")

    print(f"{'─'*40}")
    print(f"完了: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())
