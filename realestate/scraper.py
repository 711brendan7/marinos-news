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
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import gspread
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

import parsers

try:
    import anthropic
except ImportError:
    anthropic = None

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID", "")
INPUT_SHEET      = os.getenv("INPUT_SHEET", "会社リスト")
OUTPUT_SHEET     = os.getenv("OUTPUT_SHEET", "物件情報")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS", os.path.join(os.path.dirname(__file__), "credentials.json"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

OUTPUT_HEADERS = ["取得日時", "会社名", "物件名・タイトル", "価格・賃料", "所在地", "面積・間取り", "物件URL", "会社URL"]

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
    if first_row != OUTPUT_HEADERS:
        sheet.insert_row(OUTPUT_HEADERS, index=1)
        sheet.format("A1:H1", {
            "backgroundColor": {"red": 0.102, "green": 0.451, "blue": 0.914},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        })


def get_existing_property_urls(gc):
    ss = gc.open_by_key(SPREADSHEET_ID)
    sheet = ss.worksheet(OUTPUT_SHEET)
    data = sheet.get_all_values()
    if len(data) <= 1:
        return set()
    url_col = 6  # G列（0-indexed）
    return {row[url_col].strip() for row in data[1:] if len(row) > url_col and row[url_col].strip()}


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
        ]
        for p in properties
    ]
    if rows:
        sheet.insert_rows(rows, row=2, value_input_option="USER_ENTERED")


# ── Web スクレイピング ─────────────────────────────────────────

async def fetch_html(url, timeout=20):
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=HTTP_HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        print(f"    ⚠️  fetch失敗 {url}: {e}")
        return None


async def fetch_html_playwright(url, timeout=20000):
    """JavaScriptが必要なサイト向け: PlaywrightでレンダリングしてからHTMLを取得する。"""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=HTTP_HEADERS["User-Agent"])
            await page.goto(url, timeout=timeout, wait_until="networkidle")
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
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
    html = await fetch_html(url)
    if html:
        _, links = clean_html(html)
        if len(links) >= 3:
            return html
        print(f"    ⚡ JSレンダリングが必要と判断 → Playwright使用")
    html = await fetch_html_playwright(url)
    return html


async def scrape_company_parser(company_name, homepage_url, existing_urls, discover):
    """会社別パーサーで抽出（API不使用）。"""
    print(f"  🔍 {company_name}（パーサー / API不使用）: {homepage_url}")
    items = await discover(homepage_url, fetch_html)
    new_props = []
    seen_in_run = set()
    for it in items:
        url = it.get("url", "").strip()
        if not url or url in existing_urls or url in seen_in_run:
            continue  # 既出は詳細取得せずスキップ
        # discovery がカードから抽出済み（address/price を含む）なら詳細取得不要
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
            await asyncio.sleep(0.5)
        prop["company_name"] = company_name
        prop["source_url"] = homepage_url
        new_props.append(prop)
        seen_in_run.add(url)
        existing_urls.add(url)
    print(f"    ✅ {len(new_props)} 件の新規物件")
    return new_props


async def scrape_company(company_name, homepage_url, existing_urls):
    # 会社別パーサーがあれば優先（API不使用）
    if company_name in parsers.PARSERS:
        return await scrape_company_parser(
            company_name, homepage_url, existing_urls, parsers.PARSERS[company_name]
        )

    # パーサー未対応の会社は Claude API にフォールバック（キーがある場合のみ）
    if _anthropic_client is None:
        print(f"  ⏭️  {company_name}: パーサー未対応・APIキー無しのためスキップ")
        return []

    print(f"  🔍 {company_name}（AI / API使用）: {homepage_url}")

    html = await fetch_with_fallback(homepage_url)
    if not html:
        return []

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
        if dedup_key and dedup_key not in existing_urls and dedup_key not in seen_in_run:
            p["company_name"] = company_name
            p["source_url"] = homepage_url
            new_props.append(p)
            seen_in_run.add(dedup_key)
            if prop_url:
                existing_urls.add(prop_url)

    print(f"    ✅ {len(new_props)} 件の新規物件")
    return new_props


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

    gc = get_sheets_client()
    ensure_output_headers(gc)

    companies = read_company_list(gc)
    if not companies:
        print(f"⚠️  '{INPUT_SHEET}' シートに会社データがありません")
        print("   A列: 会社名、B列: URL の形式で入力してください")
        sys.exit(0)
    print(f"📋 {len(companies)} 社を巡回します\n")

    existing_urls = get_existing_property_urls(gc)
    print(f"📊 既存登録物件数: {len(existing_urls)} 件\n")

    all_new_props = []
    for company_name, url in companies:
        try:
            props = await scrape_company(company_name, url, existing_urls)
            all_new_props.extend(props)
        except Exception as e:
            print(f"    ⚠️  {company_name} でエラー（スキップ）: {e}")
        await asyncio.sleep(2)

    print(f"\n{'─'*40}")
    if all_new_props:
        append_properties(gc, all_new_props)
        print(f"✅ {len(all_new_props)} 件の新規物件を '{OUTPUT_SHEET}' シートに追記しました")
    else:
        print("📭 本日の新規物件はありませんでした")

    print(f"{'─'*40}")
    print(f"完了: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())
