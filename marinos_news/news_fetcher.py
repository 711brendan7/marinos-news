import feedparser
import pandas as pd
from datetime import datetime
import urllib.parse
import anthropic


def fetch_article_summary(title: str, api_key: str = "") -> str:
    """Claude APIを使って記事タイトルから概要を生成する。APIキーがない場合は空文字。"""
    if not api_key:
        return ""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"以下のサッカーニュース記事タイトルから、"
                        f"記事の内容を50文字以内で簡潔に説明してください。\n\n"
                        f"タイトル：{title}"
                    ),
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception:
        return ""


def fetch_marinos_news(keyword: str = "マリノス", max_items: int = 30) -> pd.DataFrame:
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
        published_dt = None
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
            "_sort_dt": published_dt,
        })

    df = pd.DataFrame(articles)

    # URL を基準に重複を除外し、新しい順に並べる
    if not df.empty:
        df = df.drop_duplicates(subset=["URL"])
        df = df.sort_values("_sort_dt", ascending=False, na_position="last")
        df = df.drop(columns=["_sort_dt"])
        df = df.reset_index(drop=True)

    return df
