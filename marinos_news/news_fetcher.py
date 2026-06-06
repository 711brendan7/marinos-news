import feedparser
import pandas as pd
from datetime import datetime
import urllib.parse
import re
import trafilatura


def fetch_article_summary(url: str, max_chars: int = 120) -> str:
    """記事URLから本文を取得し、冒頭をmax_chars文字で返す。取得できない場合は空文字。"""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        if not text:
            return ""
        # 改行を除去して冒頭を切り出す
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] + "…" if len(text) > max_chars else text
    except Exception:
        return ""


def fetch_marinos_news(keyword: str = "横浜F・マリノス", max_items: int = 30) -> pd.DataFrame:
    """
    Google ニュース RSS からキーワードに一致するニュースを取得する。
    重複URL は除外して DataFrame で返す。
    """
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

        # 日時をパースして見やすい形式に変換
        try:
            published_dt = datetime(*entry.published_parsed[:6])
            published = published_dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            published = published_raw

        articles.append({
            "タイトル": title,
            "URL": url,
            "配信元": source,
            "公開日時": published,
        })

    df = pd.DataFrame(articles)

    # URL を基準に重複を除外
    if not df.empty:
        df = df.drop_duplicates(subset=["URL"])
        df = df.reset_index(drop=True)

    return df
