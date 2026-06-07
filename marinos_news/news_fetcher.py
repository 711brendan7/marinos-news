import feedparser
import pandas as pd
from datetime import datetime, timezone, timedelta
import urllib.parse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

RSS_SOURCES = [
    {
        "name": "Google News",
        "url": None,  # キーワードで動的生成
        "keyword_in_url": True,
    },
    {
        "name": "Yahoo!ニュース",
        "url": "https://news.yahoo.co.jp/rss/topics/sports.xml",
        "keyword_in_url": False,
    },
    {
        "name": "スポニチ",
        "url": "https://www.sponichi.co.jp/soccer/rss/sponichi-20061016-soccer.xml",
        "keyword_in_url": False,
    },
    {
        "name": "日刊スポーツ",
        "url": "https://www.nikkansports.com/soccer/rss/soccer.xml",
        "keyword_in_url": False,
    },
]


def _parse_entry(entry, source_name, keyword_in_url, keyword):
    title = entry.get("title", "タイトルなし")

    # キーワードをURLに埋め込まないソースはタイトル/要約でフィルタ
    if not keyword_in_url:
        summary_raw = entry.get("summary", "")
        if keyword not in title and keyword not in summary_raw:
            return None

    url = entry.get("link", "")
    source = entry.get("source", {}).get("title", source_name)

    JST = timezone(timedelta(hours=9))
    published_dt = None
    try:
        published_utc = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        published_dt = published_utc.replace(tzinfo=None)  # naive UTC for sorting
        published = published_utc.astimezone(JST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        published = entry.get("published", "")

    summary_raw = entry.get("summary", "")
    summary = re.sub(r"<[^>]+>", "", summary_raw)
    summary = re.sub(r"\s+", " ", summary).strip()
    if len(summary) > 120:
        summary = summary[:120] + "…"

    return {
        "タイトル": title,
        "URL": url,
        "配信元": source,
        "公開日時": published,
        "要約": summary,
        "_sort_dt": published_dt,
    }


def _fetch_source(source, keyword, max_items):
    if source["keyword_in_url"]:
        encoded = urllib.parse.quote(keyword)
        url = (
            f"https://news.google.com/rss/search"
            f"?q={encoded}&hl=ja&gl=JP&ceid=JP:ja"
        )
    else:
        url = source["url"]

    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[: max_items * 3]:
        article = _parse_entry(entry, source["name"], source["keyword_in_url"], keyword)
        if article:
            articles.append(article)
        if len(articles) >= max_items:
            break
    return articles


def fetch_marinos_news(keyword: str = "マリノス", max_items: int = 30, days: int = 7) -> pd.DataFrame:
    all_articles = []

    with ThreadPoolExecutor(max_workers=len(RSS_SOURCES)) as executor:
        futures = {
            executor.submit(_fetch_source, src, keyword, max_items): src
            for src in RSS_SOURCES
        }
        for future in as_completed(futures):
            try:
                all_articles.extend(future.result())
            except Exception:
                pass

    df = pd.DataFrame(all_articles)

    if not df.empty:
        df = df.drop_duplicates(subset=["URL"])
        df = df.sort_values("_sort_dt", ascending=False, na_position="last")

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_naive = cutoff.replace(tzinfo=None)
        df = df[df["_sort_dt"].apply(lambda d: d is None or d >= cutoff_naive)]

        df = df.drop(columns=["_sort_dt"])
        df = df.reset_index(drop=True)

    return df
