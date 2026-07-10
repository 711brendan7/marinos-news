#!/usr/bin/env python3
"""REINS 売買物件 全自動スクレイパー → Google Docs"""

import asyncio
import base64
import json
import os
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

LOGIN_URL        = "https://system.reins.jp/login/main/KG/GKG001200"
USER_ID          = os.getenv("REINS_USER_ID")
PASSWORD         = os.getenv("REINS_PASSWORD")
CONDITION        = os.getenv("REINS_CONDITION", "三浦")
GAS_URL          = os.getenv("GAS_URL")
HEADLESS             = os.getenv("HEADLESS", "false").lower() == "true"
ENABLE_DOWNLOADS     = os.getenv("ENABLE_DOWNLOADS", "true").lower() == "true"
TEST_LIMIT           = int(os.getenv("TEST_LIMIT", "0"))  # 0=無制限、N=N件でストップ
LINE_CHANNEL_TOKEN   = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID         = os.getenv("LINE_USER_ID", "")

CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache.json")


def send_line_notify(message):
    if not LINE_CHANNEL_TOKEN or not LINE_USER_ID:
        return
    try:
        requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "to": LINE_USER_ID,
                "messages": [{"type": "text", "text": message}],
            },
            timeout=10,
        )
        print("📱 LINE通知送信完了")
    except Exception as e:
        print(f"⚠️  LINE通知エラー: {e}")


def _notify_new_props(new_props, sheet_url, condition, cache):
    if not LINE_CHANNEL_TOKEN or not LINE_USER_ID:
        return

    folder_meta = cache.get(f"_folder_{condition}", {})
    folder_url  = folder_meta.get("url", "")
    folder_id   = folder_meta.get("id", "")

    body_contents = [{
        "type": "text",
        "text": f"🏠 REINS新着 {len(new_props)}件（{condition}）",
        "weight": "bold",
        "size": "md",
        "wrap": True,
    }]
    for p in new_props:
        addr      = p.get("address") or f"No.{p.get('reinsNo', '')}"
        price     = f" {p.get('price')}万円" if p.get("price") else ""
        text      = f"・{addr}{price}"
        drive_url = p.get("driveUrl", "")
        m         = re.search(r'/d/([^/?]+)', drive_url) if drive_url else None
        file_id   = m.group(1) if m else None
        viewer_url = (
            f"{GAS_URL}?folderId={folder_id}&fileId={file_id}"
            if file_id and folder_id and GAS_URL else None
        )
        if viewer_url:
            body_contents.append({
                "type": "box",
                "layout": "vertical",
                "action": {"type": "uri", "label": "PDF", "uri": viewer_url},
                "contents": [{
                    "type": "text",
                    "text": text,
                    "size": "sm",
                    "wrap": True,
                    "color": "#0066CC",
                }],
            })
        else:
            body_contents.append({
                "type": "text",
                "text": text,
                "size": "sm",
                "wrap": True,
                "color": "#555555",
            })

    body_contents.append({"type": "separator", "margin": "md"})

    # フォルダは GAS 図面ビューア（最終更新の降順）で開く。Drive ネイティブは名前順固定で並び順を変えられないため。
    folder_link = (
        f"{GAS_URL}?folderId={folder_id}"
        if folder_id and GAS_URL else folder_url
    )
    if folder_link:
        body_contents.append({
            "type": "button",
            "action": {"type": "uri", "label": "📁 フォルダ", "uri": folder_link},
            "style": "link",
            "height": "sm",
            "margin": "sm",
        })
    if sheet_url:
        body_contents.append({
            "type": "button",
            "action": {"type": "uri", "label": "📊 シート", "uri": sheet_url},
            "style": "link",
            "height": "sm",
        })

    flex = {
        "type": "flex",
        "altText": f"REINS新着 {len(new_props)}件（{condition}）",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": body_contents,
                "paddingAll": "lg",
            },
        },
    }
    try:
        requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"to": LINE_USER_ID, "messages": [flex]},
            timeout=10,
        )
        print("📱 LINE通知送信完了")
    except Exception as e:
        print(f"⚠️  LINE通知エラー: {e}")


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── モーダル確実クローズ ──────────────────────────────────────
async def dismiss_dialogs(page, attempts=6):
    """表示中のモーダルを閉じる。検索ボタン等のクリックがモーダルに
    インターセプトされて 30 秒タイムアウト→実行停止するのを防ぐ。"""
    for _ in range(attempts):
        if await page.locator("[role='dialog']:visible").count() == 0:
            return True
        # OK/閉じる系ボタンがあればクリック
        for btn_text in ["OK", "はい", "確認", "閉じる", "キャンセル"]:
            close_btn = page.locator(
                f"[role='dialog'] button:has-text('{btn_text}'),"
                f".modal button:has-text('{btn_text}')"
            )
            if await close_btn.count() > 0:
                try:
                    await close_btn.first.click(timeout=1500)
                    break
                except PWTimeout:
                    pass
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
    remaining = await page.locator("[role='dialog']:visible").count()
    if remaining:
        print(f"  ⚠️  モーダルが閉じきりません（残 {remaining}）")
    return remaining == 0


# ── ローディングスピナー待機 ──────────────────────────────────
async def wait_no_loading(page, timeout=15000):
    """<div class="p-loading"> オーバーレイが消えるまで待つ。残っている間に
    クリックすると pointer events を奪われて 30 秒タイムアウト→停止するため、
    クリック前に必ず呼ぶ。"""
    try:
        await page.wait_for_selector(".p-loading", state="hidden", timeout=timeout)
    except PWTimeout:
        cnt = await page.locator(".p-loading:visible").count()
        if cnt:
            print(f"  ⚠️  ローディングが消えません（残 {cnt}）")


# ── ローディングに阻まれない安全クリック ──────────────────────
async def safe_click(page, locator, timeout=10000):
    """p-loading / モーダルに阻まれても停止せず再試行するクリック。"""
    await wait_no_loading(page)
    try:
        await locator.click(timeout=timeout)
    except PWTimeout:
        # まだ阻まれている → ローディング/モーダルを片付けて短く再試行
        await wait_no_loading(page)
        await dismiss_dialogs(page)
        await locator.scroll_into_view_if_needed()
        await locator.click(timeout=timeout)


# ── ログイン ──────────────────────────────────────────────────
async def login(page):
    print("🔑 ログイン中...")
    await page.goto(LOGIN_URL)
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except PWTimeout:
        pass

    # headless 環境でページの描画完了を待つ
    await page.wait_for_selector("input[type='text']", timeout=30000)

    # ユーザID・パスワード入力
    await page.locator("input[type='text']").first.fill(USER_ID)
    await page.locator("input[type='password']").first.fill(PASSWORD)

    # 「所属機構の規程及びガイドラインを遵守します」チェック
    # Bootstrap Vue のカスタムチェックボックスは label をクリックする必要がある
    await page.locator("label:has-text('所属機構')").click()

    await page.locator("button:has-text('ログイン'), input[value='ログイン']").first.click()
    await page.wait_for_load_state("domcontentloaded")
    print("✅ ログイン完了")


# ── ワンタッチ検索でCONDITIONにマッチする全条件テキストを列挙 ─────
async def list_conditions(page):
    """売買物件検索のワンタッチ検索からCONDITIONにマッチする条件テキスト一覧を返す"""
    await page.locator("a:has-text('売買 物件検索'), button:has-text('売買 物件検索')").first.click()
    await page.wait_for_load_state("networkidle")
    try:
        await page.locator("a:has-text('検索条件を表示'), button:has-text('検索条件を表示')").first.click(timeout=5000)
        await page.wait_for_timeout(1000)
    except PWTimeout:
        return [CONDITION]

    selects_info = await page.evaluate("""
() => Array.from(document.querySelectorAll('select')).map(s => ({
    options: Array.from(s.options).map(o => ({value: o.value, text: o.text.trim()}))
}))
""")
    seen = set()
    matching = []
    for s in selects_info:
        for o in s['options']:
            if CONDITION in o['text'] and o['value'] and o['text'] not in seen:
                matching.append(o['text'])
                seen.add(o['text'])

    # ドロップダウンを閉じる
    try:
        await page.locator("a:has-text('検索条件を表示'), button:has-text('検索条件を表示')").first.click(timeout=3000)
        await page.wait_for_timeout(300)
    except PWTimeout:
        pass

    return matching if matching else [CONDITION]


# ── ワンタッチ検索で条件を読み込み → 検索実行 ────────────────
async def search(page, condition_text):
    print(f"🔍 検索条件「{condition_text}」を読み込み中...")

    # 1. 売買物件検索ページへ遷移（既にいる場合は短いタイムアウトでスキップ）
    print("  → 売買 物件検索 をクリック")
    try:
        await page.locator("a:has-text('売買 物件検索'), button:has-text('売買 物件検索')").first.click(timeout=5000)
        await page.wait_for_load_state("networkidle")
    except PWTimeout:
        if "GBK001210" not in page.url:
            await page.goto("https://system.reins.jp/main/BK/GBK001210")
            await page.wait_for_load_state("networkidle")
    print(f"  URL: {page.url}")

    # 2. ワンタッチ検索の「検索条件を表示」をクリック（最初のもの）
    try:
        await page.locator("a:has-text('検索条件を表示'), button:has-text('検索条件を表示')").first.click(timeout=5000)
        await page.wait_for_timeout(1000)
        print("  ✅ ワンタッチ検索ドロップダウンを開きました")
    except PWTimeout:
        print("  ⚠️  検索条件を表示ボタンが見つかりません")

    # 3. 「保存した条件の選択」selectから条件を選ぶ
    matched = False
    try:
        selects_info = await page.evaluate("""
() => Array.from(document.querySelectorAll('select')).map(s => ({
    id: s.id, name: s.name,
    options: Array.from(s.options).map(o => ({value: o.value, text: o.text.trim()}))
}))
""")
        print(f"  保存条件: {len(selects_info[0]['options']) if selects_info else 0} 件")

        # condition_text に完全一致する選択肢を探して選択
        for si, s in enumerate(selects_info):
            for o in s['options']:
                if o['text'] == condition_text or condition_text in o['text']:
                    sel = page.locator("select").nth(si)
                    await sel.select_option(value=o['value'])
                    print(f"  ✅ 条件選択: {o['text']}")
                    matched = True
                    break
            if matched:
                break
    except Exception as e:
        print(f"  ⚠️  条件選択エラー: {e}")

    if not matched:
        print(f"  ⚠️  「{condition_text}」を含む条件が見つかりませんでした")

    await page.screenshot(path="debug_04_condition_selected.png")

    # 4. 「読込」ボタンをクリック → 確認モーダルを自動で閉じる
    try:
        await page.locator("button:has-text('読込'), input[value='読込']").first.click(timeout=3000)
        await page.wait_for_timeout(800)

        # 確認モーダルが出た場合は「OK」「はい」「確認」をクリック
        for btn_text in ["OK", "はい", "確認", "閉じる"]:
            try:
                ok_btn = page.locator(
                    f"[role='dialog'] button:has-text('{btn_text}'),"
                    f".modal button:has-text('{btn_text}')"
                )
                if await ok_btn.count() > 0:
                    await ok_btn.first.click(timeout=2000)
                    print(f"  ✅ モーダル「{btn_text}」をクリック")
                    await page.wait_for_timeout(500)
                    break
            except PWTimeout:
                pass

        # フォーカスをモーダル外に外すためEscも試みる
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        print("  ✅ 条件を読み込みました")
    except PWTimeout:
        print("  ⚠️  読込ボタンなし（スキップ）")

    await page.screenshot(path="debug_05_before_search.png")

    # 5. ワンタッチ検索パネルを閉じてから「検索」ボタンをクリック
    try:
        await page.wait_for_selector("[role='dialog']", state="hidden", timeout=3000)
    except PWTimeout:
        pass

    # パネルを閉じる（「検索条件を表示」を再クリックしてトグル）
    try:
        await page.locator("a:has-text('検索条件を表示'), button:has-text('検索条件を表示')").first.click(timeout=3000)
        await page.wait_for_timeout(500)
        print("  ✅ ワンタッチ検索パネルを閉じました")
    except PWTimeout:
        pass

    await page.screenshot(path="debug_05_before_search.png")

    # フォーム最下部の「検索」ボタンをスクロールして確実にクリック
    # 残存モーダルにクリックを阻まれて 30 秒詰まらないよう、先に確実に閉じる
    await dismiss_dialogs(page)
    search_btn = page.locator("button").filter(has_text=re.compile(r'^検索$')).last
    await search_btn.scroll_into_view_if_needed()
    await page.wait_for_timeout(300)
    try:
        await search_btn.click(timeout=10000)
    except PWTimeout:
        # まだモーダルに阻まれている → もう一度閉じて短いタイムアウトで再試行
        await dismiss_dialogs(page)
        await search_btn.scroll_into_view_if_needed()
        await search_btn.click(timeout=10000)

    # SPA なので URL が変わらない場合は結果の出現を待つ
    try:
        await page.wait_for_url(re.compile(r'GBK0012[2-9]|GBK001[3-9]'), timeout=8000)
    except PWTimeout:
        await page.wait_for_timeout(3000)

    print(f"✅ 検索完了 URL: {page.url}")
    await page.screenshot(path="debug_06_results.png")


# ── テーブルから物件データを抽出 ──────────────────────────────
def parse_properties(html, tab_label):
    soup = BeautifulSoup(html, "html.parser")
    properties = []

    # 結果テーブルを探す（物件番号が12桁の数字で識別）
    tables = soup.find_all("table")
    target = None
    for t in tables:
        text = t.get_text()
        if re.search(r'\d{12}', text) and ("万円" in text or "㎡" in text):
            target = t
            break
    if not target:
        return properties

    rows = target.find_all("tr")
    current = {}
    no_pattern = re.compile(r'^\d+$')

    for row in rows:
        cells = [td.get_text(separator=" ", strip=True) for td in row.find_all(["td", "th"])]
        if not cells:
            continue
        row_text = " ".join(cells)

        # 物件番号行（12桁の数字）を検出 → 新しい物件の開始
        prop_no_match = re.search(r'(\d{12})', row_text)
        if prop_no_match:
            if current:
                properties.append(current)
            current = {
                "propertyType": tab_label,
                "reinsNo": prop_no_match.group(1),
            }
            # 同じ行から可能な限り情報取得
            _extract_from_text(current, row_text)
            continue

        if current:
            _extract_from_text(current, row_text)

    if current:
        properties.append(current)

    return properties


def _extract_from_text(p, text):
    # 物件種目（売土地・売地→土地 に正規化）
    type_map = {"売土地": "土地", "売地": "土地", "売一戸建": "戸建",
                "売マンション": "区分", "売外全": "アパート", "売外一": "収益物件（区分）"}
    for raw_type, normalized in type_map.items():
        if raw_type in text:
            p["propertyType"] = normalized
            break

    # 取引態様（長いものを先にマッチ）
    torihiki = re.search(r'(専属専任|専任|一般|代理)', text)
    if torihiki:
        p.setdefault("torihiki", torihiki.group(1))

    # 取引状況
    status = re.search(r'(公開中|書面による購入申し込みのみ|売主都合で一時紹介停止中)', text)
    if status:
        p.setdefault("torihikiStatus", status.group(1))

    # 価格（最初の「X万円」または「X,XXX万円」）
    price = re.search(r'([\d,]+)万円', text)
    if price and "price" not in p:
        p["price"] = price.group(1).replace(",", "")

    # 用途地域
    yoto = re.search(r'(一低|二低|一中|二中|一住|二住|準住|近商|商業|準工|工業|工専|定めなし)', text)
    if yoto:
        p.setdefault("yoto", yoto.group(1))

    # 建ぺい率・容積率（個別に取得）
    percents = re.findall(r'(\d+)%', text)
    if len(percents) >= 2:
        p.setdefault("kenpei", percents[0] + "%")
        p.setdefault("yoseki", percents[1] + "%")

    # 土地面積（ラベル付きを優先、なければ最初の㎡値）
    area = re.search(r'(?:土地面積|土地|地積)\s*[：:\s]*([\d.]+)\s*㎡', text)
    if not area:
        area = re.search(r'([\d.]+)㎡', text)
    if area and "landArea" not in p:
        p["landArea"] = area.group(1)

    # ㎡単価・坪単価（㎡の直後に続く2つの小数万円値）
    unit_prices = re.search(r'[\d.]+㎡\s+([\d.]+)万円\s+([\d.]+)万円', text)
    if unit_prices:
        p.setdefault("sqmPrice", unit_prices.group(1))
        p.setdefault("tsuboPrice", unit_prices.group(2))

    # 接道状況
    setsu = re.search(r'(角地|一方|二方|三方|四方)', text)
    if setsu:
        p.setdefault("setsuDoStatus", setsu.group(1))

    # 接道１（方角＋距離、例: 北6.2m 北東2.7m）
    setsu1 = re.search(r'([北南東西][北南東西]?\s*[\d.]+\s*[mｍ])', text)
    if setsu1:
        p.setdefault("setsuDo1", setsu1.group(1).replace(" ", ""))

    # 所在地（都道府県を含む）
    addr = re.search(r'((?:東京都|神奈川県|千葉県|埼玉県|大阪府|京都府|兵庫県|\S+[都道府県])\S+)', text)
    if addr and "address" not in p:
        p["address"] = addr.group(1)

    # 路線・駅
    station = re.search(r'([^\s]+線)\s+([^\s]+駅?)', text)
    if station:
        p.setdefault("line", station.group(1))
        p.setdefault("station", station.group(2))

    # 交通（徒歩・バス）
    walk = re.search(r'徒歩\s*(\d+)分', text)
    if walk:
        p.setdefault("walkMinutes", walk.group(1))
    bus = re.search(r'バス\s*(\d+)分', text)
    if bus:
        p.setdefault("bus", f"バス{bus.group(1)}分")

    # 会社名
    company = re.search(r'((?:株式会社|（株）|\(株\)|有限会社|（有）).+?)(?:\s{2,}|\d{2,4}-|$)', text)
    if company:
        p.setdefault("company", company.group(1).strip())

    # 電話番号
    phone = re.search(r'(\d{2,4}-\d{2,4}-\d{3,4})', text)
    if phone:
        p.setdefault("phone", phone.group(1))


# ── 1タブ分を全ページスクレイプ ───────────────────────────────
async def extract_with_js(page):
    """ページ全体テキストを物件番号で分割して抽出（table不要）"""
    body_text = await page.evaluate("() => document.body.innerText")

    # 12桁の物件番号を区切りとしてセクション分割
    sections = re.split(r'(?=\d{12})', body_text)
    properties = []
    for section in sections:
        m = re.match(r'(\d{12})', section)
        if not m:
            continue
        prop = {"reinsNo": m.group(1), "_raw": section}
        properties.append(prop)
    return properties


def _extract_detail_fields(text):
    """詳細ページテキストから各種フィールドを抽出して dict を返す"""
    result = {}

    # 商号
    for pat in [r'商\s*号\s*[：:\s]+([^\n\t　]{2,40})',
                r'((?:株式会社|㈱|（株）|\(株\)|有限会社|㈲)[^\n\t　]{1,30})']:
        m = re.search(pat, text)
        if m:
            result["shogo"] = m.group(1).strip()
            break

    # 建ぺい率（全角/半角%、ラベルと値の間に改行・スペース・記号が入っても対応）
    for pat in [r'建ぺい率\s*[：:]\s*(\d+)\s*[%％]',
                r'建蔽率\s*[：:]\s*(\d+)\s*[%％]',
                r'建ぺい率\s+(\d+)\s*[%％]',
                r'建ぺい率\D{0,30}?(\d+)\s*[%％]',
                r'建蔽率\D{0,30}?(\d+)\s*[%％]']:
        m = re.search(pat, text)
        if m:
            result["kenpei"] = m.group(1) + "%"
            break

    # 容積率
    for pat in [r'容積率\s*[：:]\s*(\d+)\s*[%％]',
                r'容積率\s+(\d+)\s*[%％]',
                r'容積率\D{0,30}?(\d+)\s*[%％]']:
        m = re.search(pat, text)
        if m:
            result["yoseki"] = m.group(1) + "%"
            break

    # ㎡単価（戸建は表示されないことがある）
    for pat in [r'㎡単価\s*[：:]\s*([\d,.]+)\s*万円',
                r'㎡単価\D{0,20}?([\d,.]+)\s*万円',
                r'平米単価\D{0,20}?([\d,.]+)\s*万円']:
        m = re.search(pat, text)
        if m:
            result["sqmPrice"] = m.group(1).replace(",", "")
            break

    # 建物面積（戸建のみ）
    m = re.search(r'建物面積\D{0,30}?([\d.]+)\s*㎡', text)
    if m:
        result["buildingArea"] = m.group(1)

    return result


async def _visit_detail_page_for_fields(page, row):
    """図面ダウンロード後、詳細ページを訪問して各種フィールドを抽出してから戻る"""
    try:
        detail_btn = row.locator("button:has-text('詳細'), a:has-text('詳細')")
        if await detail_btn.count() == 0:
            return {}
        prev_url = page.url
        await detail_btn.first.click()
        await page.wait_for_timeout(2500)
        if page.url != prev_url:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PWTimeout:
                pass
            text = await page.evaluate("() => document.body.innerText")
            fields = _extract_detail_fields(text)
            await page.go_back()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1000)
            return fields
    except Exception:
        pass
    return {}


async def download_from_list_row(page, context, reins_no, download_dir):
    """結果一覧の行にある 図面/詳細 ボタンを直接クリックしてファイル取得。
    クリック後に発生しうる3パターンを並行検出:
      ① 新タブ/ウィンドウ open → PDF化してclose
      ② ブラウザダウンロード発火 → save_as（その後詳細ページで商号取得）
      ③ 同タブSPAナビゲーション → PDF化してgo_back（遷移中に商号取得）
    戻り値: (file_path, file_type, detail_dict)
      detail_dict のキー: shogo, kenpei, yoseki, sqmPrice, tsuboPrice
    """
    os.makedirs(download_dir, exist_ok=True)

    row = page.locator(".p-table-body-row").filter(has_text=reins_no).first
    if await row.count() == 0:
        return None, None, None

    # 図面ボタン優先、なければ詳細ボタン
    for btn_text, file_type in [("図面", "図面"), ("詳細", "詳細")]:
        btn = row.locator(f"button:has-text('{btn_text}'), a:has-text('{btn_text}')")
        if await btn.count() == 0:
            continue

        prev_url = page.url

        # ① ② を並行検出するためクリック前にタスクを作成
        new_page_task = asyncio.create_task(
            context.wait_for_event("page", timeout=5000)
        )
        download_task = asyncio.create_task(
            page.wait_for_event("download", timeout=5000)
        )
        await asyncio.sleep(0)  # タスクにリスナー登録の機会を与える

        await btn.first.click()

        done, pending = await asyncio.wait(
            [new_page_task, download_task],
            timeout=6.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        # ① 新タブが開いた
        if new_page_task in done:
            try:
                new_page = new_page_task.result()
                try:
                    await new_page.wait_for_load_state("networkidle", timeout=20000)
                except PWTimeout:
                    pass
                text = await new_page.evaluate("() => document.body.innerText")
                detail = _extract_detail_fields(text)
                file_path = os.path.join(download_dir, f"{datetime.now().strftime('%Y%m%d')}_{reins_no}_{file_type}.pdf")
                await new_page.pdf(path=file_path, format="A4")
                await new_page.close()
                return file_path, file_type, detail
            except Exception:
                pass

        # ② ダウンロードが発火した（結果一覧に留まっている → 詳細ページで商号取得）
        if download_task in done:
            try:
                dl = download_task.result()
                ext = os.path.splitext(dl.suggested_filename)[1] or ".pdf"
                file_path = os.path.join(download_dir, f"{datetime.now().strftime('%Y%m%d')}_{reins_no}_{file_type}{ext}")
                await dl.save_as(file_path)
                detail = await _visit_detail_page_for_fields(page, row)
                return file_path, file_type, detail
            except Exception:
                pass

        # ③ 同タブSPAナビゲーション（詳細ページ上で商号取得してからPDF・go_back）
        if page.url != prev_url:
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeout:
                pass
            text = await page.evaluate("() => document.body.innerText")
            detail = _extract_detail_fields(text)
            file_path = os.path.join(download_dir, f"{datetime.now().strftime('%Y%m%d')}_{reins_no}_{file_type}.pdf")
            await page.pdf(path=file_path, format="A4")
            await page.go_back()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1500)
            return file_path, file_type, detail

        # どれでもなければ次のボタンを試す
        continue

    return None, None, None


async def download_property_file(context, detail_url, reins_no, download_dir):
    """詳細ページを新タブで開いて図面(PDF)または詳細(PDF)を取得"""
    if not detail_url:
        return None, None

    os.makedirs(download_dir, exist_ok=True)
    detail_page = await context.new_page()

    try:
        await detail_page.goto(detail_url, wait_until="networkidle", timeout=30000)
        await detail_page.wait_for_timeout(1000)

        # 図面リンクを探す
        zumen_loc = None
        for kw in ["図面", "物件図面", "建物図面", "間取り図"]:
            loc = detail_page.locator(f"a:has-text('{kw}'), button:has-text('{kw}')")
            if await loc.count() > 0:
                zumen_loc = loc.first
                break

        if zumen_loc:
            # 図面ダウンロードを試みる
            try:
                async with detail_page.expect_download(timeout=15000) as dl_info:
                    await zumen_loc.click()
                dl = await dl_info.value
                ext = os.path.splitext(dl.suggested_filename)[1] or ".pdf"
                file_path = os.path.join(download_dir, f"{datetime.now().strftime('%Y%m%d')}_{reins_no}_図面{ext}")
                await dl.save_as(file_path)
                return file_path, "図面"
            except PWTimeout:
                # インライン表示の場合はスクリーンショット
                await detail_page.wait_for_timeout(1000)
                file_path = os.path.join(download_dir, f"{datetime.now().strftime('%Y%m%d')}_{reins_no}_図面.png")
                await detail_page.screenshot(path=file_path, full_page=True)
                return file_path, "図面"
        else:
            # 詳細ページをPDF化
            file_path = os.path.join(download_dir, f"{datetime.now().strftime('%Y%m%d')}_{reins_no}_詳細.pdf")
            await detail_page.pdf(path=file_path, format="A4")
            return file_path, "詳細"

    except Exception as e:
        print(f"⚠️  {reins_no} ファイルエラー: {e}")
        return None, None
    finally:
        await detail_page.close()


def create_drive_folder(condition):
    """Google DriveにREINSフォルダを作成して {id, url} を返す"""
    payload = {"action": "createFolder", "folderName": f"REINS_{condition}"}
    try:
        session = requests.Session()
        resp = session.post(GAS_URL, json=payload, timeout=30, allow_redirects=True)
        data = resp.json()
        if data.get("status") == "ok":
            return {"id": data["folderId"], "url": data.get("folderUrl", "")}
        print(f"  ⚠️  フォルダ作成エラー: {data.get('message')}")
    except Exception as e:
        print(f"  ⚠️  フォルダ作成エラー: {e}")
    return None


def upload_to_drive(file_path, folder_id):
    """ファイルをbase64エンコードしてGAS経由でDriveにアップロード"""
    try:
        with open(file_path, "rb") as f:
            raw = f.read()
        content = base64.b64encode(raw).decode()
        ext = os.path.splitext(file_path)[1].lower()
        mime = "application/pdf" if ext == ".pdf" else "image/png"
        payload = {
            "action": "uploadFile",
            "fileName": os.path.basename(file_path),
            "base64": content,
            "mimeType": mime,
            "folderId": folder_id,
        }
        session = requests.Session()
        # GAS はタイムアウトやペイロード過大時に JSON でなく空/HTMLを返すため
        # レスポンス内容を表に出し、1回だけリトライする
        for attempt in range(2):
            resp = session.post(GAS_URL, json=payload, timeout=120, allow_redirects=True)
            try:
                data = resp.json()
            except ValueError:
                if attempt == 0:
                    continue
                print(f"⚠️  アップロード失敗: HTTP {resp.status_code} / "
                      f"{len(raw)//1024}KB / resp={resp.text[:120]!r}")
                return ""
            if data.get("status") == "ok":
                return data.get("fileUrl", "")
            print(f"⚠️  アップロードGASエラー: {data.get('message')}")
            return ""
    except Exception as e:
        print(f"⚠️  アップロードエラー: {e}")
    return ""


async def scrape_tab(page, tab_label, known_ids=None):
    print(f"\n📋 {tab_label} をスクレイプ中...")
    all_props = []
    page_num = 1

    while True:
        print(f"  ページ {page_num} ...", end=" ", flush=True)

        # 物件番号が描画されるまで待機（最大10秒）
        for _ in range(10):
            count = await page.evaluate("() => (document.body.innerText.match(/\\d{12}/g)||[]).length")
            if count > 0:
                break
            await page.wait_for_timeout(1000)

        # JavaScriptで直接DOMから抽出
        raw_props = await extract_with_js(page)

        # _raw テキストを既存の抽出関数でパース
        props = []
        for r in raw_props:
            p = {"reinsNo": r["reinsNo"], "propertyType": tab_label}
            _extract_from_text(p, r["_raw"])
            props.append(p)

        print(f"{len(props)} 件取得")
        all_props.extend(props)

        # 新規追加のみモード: このページが全件既知なら以降をスキップ
        if known_ids is not None and props and all(p["reinsNo"] in known_ids for p in props):
            print(f"  → ページ {page_num} の全件が既知 → 以降のページをスキップ")
            break

        # 次ページリンクを探す
        next_link = page.locator("a:has-text('次'), a[title='次ページ'], a:has-text('>')").last
        try:
            if await next_link.is_visible():
                await next_link.click()
                await page.wait_for_load_state("domcontentloaded")
                page_num += 1
            else:
                break
        except PWTimeout:
            break

    print(f"  → 合計 {len(all_props)} 件")
    return all_props


async def download_phase(page, context, all_properties, condition):
    """結果一覧の 図面/詳細 ボタンを直接クリックして Drive にアップロード。
    cache.json で既DL済みをスキップし、条件ごとに永続フォルダを再利用する。
    """
    print(f"\n📥 図面/詳細ダウンロード開始（{len(all_properties)} 件）")

    # ── キャッシュ・フォルダ準備 ──────────────────────────────────
    cache = load_cache()
    cache_key_folder = f"_folder_{condition}"

    if cache_key_folder in cache:
        folder_id  = cache[cache_key_folder]["id"]
        folder_url = cache[cache_key_folder]["url"]
        print(f"  📁 既存Driveフォルダを利用: {folder_url}")
    else:
        result = create_drive_folder(condition)
        if not result:
            print("⚠️  Driveフォルダ作成失敗 → スキップ")
            return
        folder_id  = result["id"]
        folder_url = result["url"]
        cache[cache_key_folder] = {"id": folder_id, "url": folder_url}
        save_cache(cache)
        print(f"  📁 Driveフォルダ: {folder_url}")

    download_dir = os.path.join(os.path.dirname(__file__),
                                f"files_{datetime.now().strftime('%Y%m%d_%H%M')}")

    # ── 種別ごとにグループ化してタブ操作 ─────────────────────────
    by_type = {}
    for prop in all_properties:
        t = prop.get("propertyType", "物件")
        by_type.setdefault(t, []).append(prop)

    tab_type_map = {"土地": "売土地", "戸建": "売一戸建", "区分": "売マンション", "アパート": "売外全",
                    "マンション": "売マンション", "収益物件（一棟）": "売外全"}

    for prop_type, props in by_type.items():
        print(f"\n  📂 {prop_type} タブ（{len(props)} 件）")

        tab_text = tab_type_map.get(prop_type, prop_type)
        tab_loc = page.locator("a").filter(has_text=re.compile(tab_text))
        if await tab_loc.count() > 0:
            await safe_click(page, tab_loc.first)
        else:
            print(f"    ⚠️  {tab_text} タブが見つかりません")
            continue

        for _ in range(15):
            cnt = await page.evaluate("() => (document.body.innerText.match(/\\d{12}/g)||[]).length")
            if cnt > 0:
                break
            await page.wait_for_timeout(1000)

        target_props = props[:TEST_LIMIT] if TEST_LIMIT > 0 else props
        for i, prop in enumerate(target_props):
            reins_no   = prop["reinsNo"]
            cache_key  = f"{condition}_{reins_no}"

            # ── キャッシュヒット: ダウンロードをスキップ ──────────
            if cache_key in cache:
                cached = cache[cache_key]
                prop.update({
                    "driveUrl":    cached["driveUrl"],
                    "fileType":    cached["fileType"],
                    "shogo":       cached.get("shogo", ""),
                    "kenpei":      cached.get("kenpei", "") or prop.get("kenpei", ""),
                    "yoseki":      cached.get("yoseki", "") or prop.get("yoseki", ""),
                    "sqmPrice":    cached.get("sqmPrice", "") or prop.get("sqmPrice", ""),
                    "tsuboPrice":  cached.get("tsuboPrice", "") or prop.get("tsuboPrice", ""),
                    "buildingArea": cached.get("buildingArea", ""),
                    "fetchedAt":   cached["fetchedAt"],
                    "folderUrl":   folder_url,
                    "address":      cached.get("address", "") or prop.get("address", ""),
                    "price":        cached.get("price", "") or prop.get("price", ""),
                    "propertyType": cached.get("propertyType", "") or prop.get("propertyType", ""),
                })
                print(f"    [{i+1}/{len(target_props)}] {reins_no} ... キャッシュ済み")
                continue

            # ── 新規: ダウンロード → アップロード ────────────────
            print(f"    [{i+1}/{len(target_props)}] {reins_no} ...", end=" ", flush=True)
            file_path, file_type, detail = await download_from_list_row(
                page, context, reins_no, download_dir)

            fetched_at = datetime.now().strftime("%Y/%m/%d %H:%M")
            detail = detail or {}

            if file_path:
                drive_url = upload_to_drive(file_path, folder_id)
                prop.update({
                    "driveUrl":  drive_url or "",
                    "fileType":  file_type or "",
                    "fetchedAt": fetched_at,
                    "folderUrl": folder_url,
                })
                # 詳細ページで取得したフィールドで上書き（空の場合のみ）
                for field in ["shogo", "kenpei", "yoseki", "sqmPrice", "tsuboPrice", "buildingArea"]:
                    if detail.get(field) and not prop.get(field):
                        prop[field] = detail[field]
                # 戸建: ㎡単価が未取得なら 価格÷土地面積 で計算
                if prop.get("propertyType") == "戸建" and prop.get("price") and prop.get("landArea") and not prop.get("sqmPrice"):
                    try:
                        sqm = round(float(str(prop["price"]).replace(",", "")) / float(prop["landArea"]), 1)
                        prop["sqmPrice"] = str(sqm)
                    except (ValueError, TypeError):
                        pass
                # 坪単価が未取得なら㎡単価から計算（1坪 = 3.3058㎡）
                if prop.get("sqmPrice") and not prop.get("tsuboPrice"):
                    try:
                        prop["tsuboPrice"] = str(round(float(str(prop["sqmPrice"]).replace(",", "")) * 3.3058, 1))
                    except (ValueError, TypeError):
                        pass
                if drive_url:
                    cache[cache_key] = {
                        "driveUrl":    drive_url,
                        "fileType":    file_type or "",
                        "shogo":       prop.get("shogo", ""),
                        "kenpei":      prop.get("kenpei", ""),
                        "yoseki":      prop.get("yoseki", ""),
                        "sqmPrice":    prop.get("sqmPrice", ""),
                        "tsuboPrice":  prop.get("tsuboPrice", ""),
                        "buildingArea": prop.get("buildingArea", ""),
                        "fetchedAt":    fetched_at,
                        "address":      prop.get("address", ""),
                        "price":        prop.get("price", ""),
                        "propertyType": prop.get("propertyType", ""),
                    }
                    save_cache(cache)
                    shogo_str = f" 商号:{prop.get('shogo')}" if prop.get("shogo") else ""
                    print(f"{file_type} → Drive ✓{shogo_str}")
                else:
                    # アップロード失敗: シート追記も sent 登録もせず次回再試行させる
                    prop["_upload_failed"] = True
                    print("⚠️  アップロード失敗（シート追記を保留・次回再試行）")
                try:
                    os.remove(file_path)
                except OSError:
                    pass
            else:
                prop.update({
                    "driveUrl":  "",
                    "fileType":  "",
                    "fetchedAt": fetched_at,
                    "folderUrl": folder_url,
                })
                print("失敗")

    try:
        os.rmdir(download_dir)
    except OSError:
        pass


# ── GAS へ POST して結果を返す ────────────────────────────────
def _post_to_gas(payload):
    session = requests.Session()
    session.max_redirects = 5
    resp = session.post(GAS_URL, json=payload, timeout=180, allow_redirects=True)
    print(f"  HTTP {resp.status_code}, Content-Type: {resp.headers.get('Content-Type','')}")
    try:
        return resp.json()
    except Exception:
        print(f"⚠️  レスポンスをJSONとして解析できません: {resp.text[:200]}")
        return {}


# ── Google Spreadsheet に送信（初回: 全件作成 / 以降: 新規追記）─
def send_to_sheets(all_properties, condition):
    if not GAS_URL:
        out = f"reins_result_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(all_properties, f, ensure_ascii=False, indent=2)
        print(f"💾 保存: {out}")
        return

    cache = load_cache()
    ss_url_key   = f"_spreadsheet_{condition}"
    sent_set_key = f"_sheet_sent_{condition}"

    existing_url = cache.get(ss_url_key)
    sent_set     = set(cache.get(sent_set_key, []))

    # 内部キー(_raw, _is_new 等)を除去
    def clean(p):
        return {k: v for k, v in p.items() if not k.startswith("_")}

    # アップロード失敗物件(_upload_failed)は sent 登録も追記もせず次回に持ち越す
    new_props = [p for p in all_properties
                 if p.get("reinsNo") not in sent_set and not p.get("_upload_failed")]

    if existing_url and new_props:
        # ── 既存スプレッドシートに追記 ──────────────────────────
        m = re.search(r'/spreadsheets/d/([^/]+)', existing_url)
        ss_id = m.group(1) if m else None
        if not ss_id:
            existing_url = None  # 無効なURL → 新規作成へ

    if not existing_url:
        # ── 初回: スプレッドシートを新規作成 ───────────────────
        print(f"\n📤 Google Spreadsheetsに送信中... ({len(all_properties)}件)")
        data = _post_to_gas({
            "action": "createSheet",
            "properties": [clean(p) for p in all_properties],
            "condition": condition,
        })
        if data.get("status") == "ok":
            url = data.get("sheetUrl", "")
            cache[ss_url_key] = url
            for p in all_properties:
                sent_set.add(p.get("reinsNo", ""))
            cache[sent_set_key] = list(sent_set)
            save_cache(cache)
            print(f"✅ Google Spreadsheet 作成完了！\n   {url}")
            return url, list(all_properties)
        else:
            print(f"⚠️  GASエラー: {data.get('message')}")

    elif new_props:
        # ── 差分追記 ───────────────────────────────────────────
        m = re.search(r'/spreadsheets/d/([^/]+)', existing_url)
        ss_id = m.group(1)
        print(f"\n📤 新規物件 {len(new_props)}件 を追記中...")
        data = _post_to_gas({
            "action": "appendToSheet",
            "spreadsheetId": ss_id,
            "properties": [clean(p) for p in new_props],
        })
        if data.get("status") == "ok":
            for p in new_props:
                sent_set.add(p.get("reinsNo", ""))
            cache[sent_set_key] = list(sent_set)
            save_cache(cache)
            print(f"✅ 追記完了！\n   {existing_url}")
            return existing_url, list(new_props)
        elif data.get("status") == "notFound":
            # スプレッドシートが削除された → キャッシュをリセットして再作成
            print("⚠️  スプレッドシートが見つかりません。新規作成します。")
            del cache[ss_url_key]
            cache[sent_set_key] = []
            save_cache(cache)
            return send_to_sheets(all_properties, condition)
        else:
            print(f"⚠️  GASエラー: {data.get('message')}")

    else:
        # ── 新規なし ────────────────────────────────────────────
        print(f"\n✅ 新規物件なし。スプレッドシートを更新しません。\n   {existing_url}")
        return existing_url, []

    return None, []


# ── メイン ────────────────────────────────────────────────────
async def main():
    if not USER_ID or not PASSWORD:
        print("❌ .env に REINS_USER_ID と REINS_PASSWORD を設定してください")
        sys.exit(1)

    all_properties = []
    tab_type_map = {"売土地": "土地", "売地": "土地", "売一戸建": "戸建",
                    "売マンション": "区分", "売外全": "アパート", "売外一": "収益物件（区分）"}

    # 既送信済みの物件番号を取得（新規追加のみモード用）
    cache = load_cache()
    known_ids = set(cache.get(f"_sheet_sent_{CONDITION}", []))
    if known_ids:
        print(f"📦 既知物件: {len(known_ids)} 件（新規のみ取得モード）")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context()
        page = await context.new_page()

        await login(page)

        # CONDITIONにマッチする全保存条件を列挙
        conditions = await list_conditions(page)
        print(f"📋 実行条件 ({len(conditions)}件): {', '.join(conditions)}")

        for cond_text in conditions:
            await search(page, cond_text)

            cond_props = []
            tabs = page.locator("a").filter(
                has_text=re.compile(r'売土地|売一戸建|売マンション|売外全|売外一'))
            tab_count = await tabs.count()

            if tab_count == 0:
                props = await scrape_tab(page, "物件", known_ids=known_ids or None)
                cond_props.extend(props)
            else:
                for i in range(tab_count):
                    tab = tabs.nth(i)
                    raw_label = (await tab.inner_text()).strip()
                    label = re.sub(r'[\(（].*', '', raw_label).strip()
                    label = tab_type_map.get(label, label)
                    print(f"\n🗂  タブ切替: {raw_label}")
                    await tab.click()
                    await page.wait_for_timeout(1500)
                    props = await scrape_tab(page, label, known_ids=known_ids or None)
                    cond_props.extend(props)

            # 条件ごとにダウンロード（ブラウザが検索結果ページにある間に実行）
            if ENABLE_DOWNLOADS and GAS_URL:
                await download_phase(page, context, cond_props, CONDITION)

            all_properties.extend(cond_props)

        await browser.close()

    print(f"\n🏠 合計 {len(all_properties)} 件取得")
    if len(all_properties) == 0:
        print("⚠️  物件が取得できませんでした。debug_*.png を確認してください。")
        return
    sheet_url, new_props = send_to_sheets(all_properties, CONDITION)
    cache = load_cache()
    if new_props and sheet_url:
        _notify_new_props(new_props, sheet_url, CONDITION, cache)
    else:
        sheet_url = sheet_url or cache.get(f"_spreadsheet_{CONDITION}", "")
        send_line_notify(f"✅ REINS確認完了（新着なし）\n📊 シート: {sheet_url}")


if __name__ == "__main__":
    asyncio.run(main())
