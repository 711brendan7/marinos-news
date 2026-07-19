#!/usr/bin/env python3
"""
会社別パーサー（API不使用）

各社は「物件詳細ページURLの発見（売買のみ）」だけを実装し、
共通の詳細テーブル解析 parse_detail() で 価格/所在地/面積/間取り を抽出する。
reins と同じくサイト構造に依存した決め打ち方式。サイト改装時は該当社の
discovery 関数のみ修正すればよい。
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# ── 共通ヘルパ ────────────────────────────────────────────────

RENTAL_KEYWORDS = ["月額", "/月", "円/月", "万円/月", "賃料", "家賃", "敷金", "礼金"]

def is_rental(text: str) -> bool:
    return any(kw in (text or "") for kw in RENTAL_KEYWORDS)


def norm_price(s: str) -> str:
    """価格文字列を「2,280万円」「1億2,000万円」の形に正規化。売買価格が無ければ空。"""
    if not s:
        return ""
    t = s.replace(" ", "").replace("　", "")
    m = re.search(r"\d[\d,]*(?:\.\d+)?億(?:\d[\d,]*万?)?円", t)
    if m:
        return m.group(0)
    m = re.search(r"\d[\d,]*(?:\.\d+)?万円", t)
    if m:
        return m.group(0)
    return ""


def norm_area(s: str) -> str:
    """面積文字列から「89.24㎡」を抜き出す。"""
    if not s:
        return ""
    # 「m 2」「m2」「m²」→「㎡」。全角スペースは除去するが半角スペースは残す
    # （隣接する数字が結合して誤った面積になるのを防ぐ）
    t = re.sub(r"m\s*2", "㎡", s).replace("m²", "㎡").replace("　", "")
    m = re.search(r"\d[\d,]*(?:\.\d+)?\s*㎡", t)
    return m.group(0).replace(" ", "") if m else ""


def extract_layout(s: str) -> str:
    """間取り（3LDK / ワンルーム 等）を抜き出す。該当なしは空。"""
    if not s:
        return ""
    t = s.replace(" ", "").replace("　", "")
    m = re.search(r"\d[SLDKR]{1,4}", t)
    if m:
        return m.group(0)
    if "ワンルーム" in t or t.startswith("1R"):
        return "ワンルーム"
    return ""


def extract_address(text: str) -> str:
    if not text:
        return ""
    # 都道府県付きを優先（例: 神奈川県横須賀市佐島３丁目）
    m = re.search(r"(?:[^\s、。「]{2,4}県)[^\s、。「]*?[市区町村][^\s、。「0-9]*", text)
    if m:
        return m.group(0).strip()
    # 県なしフォールバック（市・町のみ。「区画図」等の誤ヒットを避けるため区は使わない）
    m = re.search(r"[^\s、。「0-9]{0,6}[市町][^\s、。「0-9]*", text)
    if m and "区画" not in m.group(0) and "図" not in m.group(0):
        return m.group(0).strip()
    return ""


def _valid_value(key: str, value: str) -> bool:
    """ヘッダー行由来のゴミ（ラベルがラベルとペアになったもの）を弾く。"""
    if not value:
        return False
    if key == "price":
        return bool(norm_price(value))
    if key in ("building_area", "land_area"):
        return bool(norm_area(value))
    if key == "layout":
        return bool(extract_layout(value))
    if key == "address":
        return any(c in value for c in "県市区町村")
    if key == "type":
        return any(k in value for k in ("戸建", "マンション", "土地", "一戸建"))
    return True


# ラベル → 内部キー
_LABELS = {
    "price":         ["価格", "販売価格", "物件価格"],
    "address":       ["所在地", "住所", "住　所"],
    "layout":        ["間取り", "間取"],
    "building_area": ["建物面積"],
    "land_area":     ["土地面積", "地積"],
    "type":          ["物件種目", "種目", "種別"],
}


def _label_key(label: str):
    label = (label or "").strip()
    for key, names in _LABELS.items():
        if any(label == n or label.startswith(n) for n in names):
            return key
    return None


def parse_detail(html: str, url: str, hints: dict = None) -> dict:
    """詳細ページHTMLから物件情報を抽出。hints で discovery 側の補完値を渡せる。"""
    hints = hints or {}
    soup = BeautifulSoup(html, "html.parser")

    fields = {}
    # テーブルの (ラベル, 値) ペアを収集（同一 tr 内で隣接セルをペア化）
    # 値がその key として妥当なもののみ採用（ヘッダー行のゴミを排除）
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        for i in range(0, len(cells) - 1, 2):
            key = _label_key(cells[i])
            if key and key not in fields and _valid_value(key, cells[i + 1]):
                fields[key] = cells[i + 1]

    # 価格
    price = norm_price(fields.get("price", "")) or norm_price(hints.get("price_hint", ""))
    if not price:
        price = norm_price(soup.get_text(" ", strip=True))

    # 賃貸除外
    if is_rental(fields.get("price", "") + " " + hints.get("price_hint", "")):
        return {}

    # 面積・間取り（建物面積を優先、無ければ土地面積）
    area = norm_area(fields.get("building_area", "")) or norm_area(fields.get("land_area", ""))
    layout = extract_layout(fields.get("layout", ""))
    area_layout = " / ".join(x for x in [area, layout] if x)

    # 所在地（テーブル → h1/h2 や本文から補完）
    address = fields.get("address", "").strip()
    if not address:
        for h in soup.find_all(["h1", "h2"]):
            address = extract_address(h.get_text(" ", strip=True))
            if address:
                break

    # タイトル（種別＋所在地 を優先。無ければ h1、最後に所在地）
    title = hints.get("title_hint", "").strip()
    if not title:
        ptype = fields.get("type", "").replace(" ", "")
        if ptype and address:
            title = f"{ptype} {address}"
        elif address:
            title = address
    if not title:
        for h in soup.find_all(["h1", "h2"]):
            t = h.get_text(" ", strip=True)
            if t:
                title = t[:60]
                break

    if not (title or address):
        return {}

    return {
        "title": title,
        "price": price,
        "address": address,
        "area_layout": area_layout,
        "url": url,
    }


# ── 会社別 discovery ──────────────────────────────────────────
# 各 discovery は async def f(homepage_url, fetch) -> list[{url, price_hint, title_hint}]
# fetch(url) は HTML文字列 or None を返す非同期関数。

async def discover_katou(homepage_url, fetch):
    """加藤不動産: /buy の /estate/eb*（売買）リンクを収集。er* は賃貸なので除外。"""
    html = await fetch(urljoin(homepage_url, "/buy"))
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(homepage_url, a["href"])
        # 売買のみ: /estate/eb...  （賃貸 /estate/er... は除外）
        if not re.search(r"/estate/eb[a-z]/", full):
            continue
        if full in seen:
            continue
        seen.add(full)
        txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        out.append({
            "url": full,
            "price_hint": norm_price(txt),
            "title_hint": "",
        })
    return out


async def discover_saito(homepage_url, fetch):
    """サイトウ住宅: 売買カテゴリ配下の detail-* を収集。"""
    cats = ["/kodate/", "/mansion/", "/uri-tochi/"]  # 一戸建て・マンション・売土地（賃貸/貸土地は除外）
    out, seen = [], set()
    for cat in cats:
        for path in (cat, cat + "kanagawa/"):
            html = await fetch(urljoin(homepage_url, path))
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                full = urljoin(homepage_url, a["href"])
                if "/detail-" not in full:
                    continue
                full = full.split("#")[0]
                if full in seen:
                    continue
                seen.add(full)
                out.append({"url": full, "price_hint": "", "title_hint": ""})
    return out


async def discover_marufuji(homepage_url, fetch):
    """マルフジ住宅: トップから miurahanto.com/detail/marufuji/*.html を収集。"""
    html = await fetch(homepage_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(homepage_url, a["href"])
        if not re.search(r"miurahanto\.com/detail/marufuji/.+\.html$", full):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append({"url": full, "price_hint": "", "title_hint": ""})
    return out


_PROP_TYPES = ["中古マンション", "新築マンション", "中古一戸建て", "新築一戸建て",
               "中古戸建", "新築戸建", "売地", "土地", "マンション", "一戸建て", "戸建"]

def _detect_type(text: str) -> str:
    for t in _PROP_TYPES:
        if t in text:
            return t
    return ""


async def discover_livable(homepage_url, fetch):
    """東急リバブル: 検索結果カードから直接抽出（詳細ページ不要・売買のみ）。
    設定URLから賃貸(chintai-*)を除いた売買URLに変換し、ページ送りで全件収集する。"""
    m = re.search(r"conditions-type=([^/]+)", homepage_url)
    if m:
        kounyu = [t for t in m.group(1).split(",") if t.startswith("kounyu")]
        if kounyu:
            homepage_url = re.sub(r"conditions-type=[^/]+",
                                  "conditions-type=" + ",".join(kounyu), homepage_url)
    if "mode=image" not in homepage_url:
        homepage_url += ("&" if "?" in homepage_url else "?") + "mode=image"

    out, seen = [], set()
    for page in range(1, 16):
        url = homepage_url + f"&page={page}"
        html = await fetch(url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all("div", class_=re.compile("PropertyListCard"))
        if not cards:
            break
        added = 0
        for card in cards:
            a = card.find("a", href=re.compile(r"/kounyu/inquiry/[A-Z0-9]+/"))
            if not a:
                continue
            purl = urljoin(url, a["href"]).split("?")[0]
            if purl in seen:
                continue
            seen.add(purl)
            text = re.sub(r"\s+", " ", card.get_text(" ", strip=True))
            if is_rental(text):
                continue
            price = norm_price(text)
            address = extract_address(text)
            layout = extract_layout(text)
            area = norm_area(text)
            ptype = _detect_type(text)
            title = " ".join(x for x in [ptype, address] if x) or (a.get("title") or "")[:40]
            out.append({
                "url": purl,
                "title": title,
                "price": price,
                "address": address,
                "area_layout": " / ".join(x for x in [area, layout] if x),
            })
            added += 1
        if added == 0:
            break
    return out


async def discover_rehouse(homepage_url, fetch):
    """三井のリハウス: キーワード検索結果から /buy/*/bkdetail/*/ を収集（ページ送り対応）。"""
    base = homepage_url.split("&page=")[0]
    out, seen = [], set()
    for page in range(1, 16):
        url = base + (f"&page={page}" if "?" in base else f"?page={page}")
        html = await fetch(url)
        if not html:
            break
        found = re.findall(r"/buy/[a-z]+/bkdetail/[A-Z0-9]+/", html)
        new = 0
        for path in dict.fromkeys(found):
            full = urljoin(url, path)
            if full in seen:
                continue
            seen.add(full)
            out.append({"url": full, "price_hint": "", "title_hint": ""})
            new += 1
        if new == 0:
            break
    return out


# 会社名 → discovery 関数
PARSERS = {
    "加藤不動産": discover_katou,
    "サイトウ住宅": discover_saito,
    "マルフジ住宅": discover_marufuji,
    "東急リバブル": discover_livable,
    "三井のリハウス": discover_rehouse,
}
