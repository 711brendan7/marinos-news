import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/search"


def fetch_youtube_videos(
    keyword: str = "横浜Fマリノス",
    max_items: int = 10,
    days: int = 7,
    api_key: str = "",
) -> pd.DataFrame:
    if not api_key:
        return pd.DataFrame()

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "order": "date",
        "maxResults": min(max_items, 50),
        "publishedAfter": published_after,
        "regionCode": "JP",
        "relevanceLanguage": "ja",
        "key": api_key,
    }

    try:
        response = requests.get(YOUTUBE_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return pd.DataFrame()

    videos = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId", "")
        if not video_id:
            continue

        title = snippet.get("title", "タイトルなし")
        channel = snippet.get("channelTitle", "不明")
        published_raw = snippet.get("publishedAt", "")
        url = f"https://www.youtube.com/watch?v={video_id}"

        published_dt = None
        published_str = published_raw
        try:
            published_dt = datetime.strptime(published_raw, "%Y-%m-%dT%H:%M:%SZ")
            published_str = published_dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

        description = snippet.get("description", "").replace("\n", " ").strip()
        if len(description) > 120:
            description = description[:120] + "…"

        videos.append({
            "タイトル": title,
            "URL": url,
            "配信元": f"YouTube / {channel}",
            "公開日時": published_str,
            "要約": description,
        })

    return pd.DataFrame(videos)
