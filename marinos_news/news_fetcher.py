import feedparser
import pandas as pd
from datetime import datetime
import urllib.parse
import re


def fetch_marinos_news(keyword: str = "マリノス", max_items: int = 30) -> pd.DataFrame:
    encoded_keyword = urllib.parse.quote(keyword)
    rss_url = (
        f"https://news.google.com/rss/search"
        f"?q={encoded_keyword}&hl=ja&gl=JP&ceid=JP:ja"
    )

    feed = feedparser.parse(rss_url)
    articles = []

    for entry in feed.entries[:max_items]:
        title = entry.get("title", "タイトルなし")
        url = entry.get("link", "")
        source = entry.get("source", {}).get("title", "不明")
        published_raw = entry.get("published", "")

        published_dt = None
        try:
            published_dt = datetime(*entry.published_parsed[:6])
            published = published_dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            published = published_raw

        # RSSに含まれる記事概要を取得
        summary_raw = entry.get("summary", "")
        summary = re.sub(r"<[^>]+>", "", summary_raw)  # HTMLタグを除去
        summary = re.sub(r"\s+", " ", summary).strip()
        if len(summary) > 120:
            summary = summary[:120] + "…"

        articles.append({
            "タイトル": title,
            "URL": url,
            "配信元": source,
            "公開日時": published,
            "要約": summary,
            "_sort_dt": published_dt,
        })

    df = pd.DataFrame(articles)

    if not df.empty:
        df = df.drop_duplicates(subset=["URL"])
        df = df.sort_values("_sort_dt", ascending=False, na_position="last")
        df = df.drop(columns=["_sort_dt"])
        df = df.reset_index(drop=True)

    return df
