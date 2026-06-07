import json
import streamlit as st
import pandas as pd
from streamlit_javascript import st_javascript
from news_fetcher import fetch_marinos_news
from youtube_fetcher import fetch_youtube_videos

st.set_page_config(
    page_title="サッカー 最新ニュース",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ サッカー 最新ニュース")
st.caption("Google ニュース・スポニチ・日刊スポーツ・YouTube の情報を取得しています")

# ── localStorage から既読URLを読み込む ──────────────────────────
raw = st_javascript("JSON.parse(localStorage.getItem('marinos_read_urls') || '[]')")
if isinstance(raw, list):
    st.session_state.read_urls = set(raw)
elif "read_urls" not in st.session_state:
    st.session_state.read_urls = set()


def mark_read(url: str):
    st.session_state.read_urls.add(url)
    urls_json = json.dumps(list(st.session_state.read_urls))
    st_javascript(f"localStorage.setItem('marinos_read_urls', JSON.stringify({urls_json}))")


def unmark_read(url: str):
    st.session_state.read_urls.discard(url)
    urls_json = json.dumps(list(st.session_state.read_urls))
    st_javascript(f"localStorage.setItem('marinos_read_urls', JSON.stringify({urls_json}))")


# ── サイドバー ────────────────────────────────────────────────
with st.sidebar:
    st.header("設定")

    st.subheader("カテゴリ")
    chk_marinos = st.checkbox("横浜F・マリノス", value=True)
    chk_japan   = st.checkbox("サッカー日本代表", value=False)
    chk_maeda   = st.checkbox("前田大然", value=False)
    custom_keyword = st.text_input("カスタムキーワード（任意）", value="", placeholder="例：久保建英")

    st.subheader("オプション")
    max_items = st.slider("最大取得件数（カテゴリごと）", min_value=5, max_value=50, value=20, step=5)
    days = st.slider("過去N日以内", min_value=1, max_value=30, value=3, step=1)
    youtube_enabled = st.checkbox("YouTube動画も取得する", value=True)
    show_read = st.checkbox("既読記事も表示する", value=False)

    fetch_button = st.button("ニュースを取得する", type="primary")

KEYWORD_MAP = {
    "横浜F・マリノス": "マリノス",
    "サッカー日本代表": "サッカー日本代表",
    "前田大然": "前田大然",
}

selected = []
if chk_marinos: selected.append("横浜F・マリノス")
if chk_japan:   selected.append("サッカー日本代表")
if chk_maeda:   selected.append("前田大然")
if custom_keyword.strip():
    KEYWORD_MAP[custom_keyword.strip()] = custom_keyword.strip()
    selected.append(custom_keyword.strip())


def render_articles(df: pd.DataFrame, prefix: str):
    displayed = 0
    for i, row in df.iterrows():
        url = row["URL"]
        is_read = url in st.session_state.read_urls

        if is_read and not show_read:
            continue

        displayed += 1
        col_text, col_btn, col_check = st.columns([8, 2, 1])

        with col_text:
            summary = row["要約"]
            if is_read:
                st.markdown(
                    f'<span style="color:#bbb;text-decoration:line-through;">{summary}</span>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(summary)
            st.caption(f'{row["配信元"]} ｜ {row["公開日時"]}')

        with col_btn:
            safe_url = url.replace("'", "%27")
            st.markdown(
                f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
                f'onclick="'
                f'var u=JSON.parse(localStorage.getItem(\'marinos_read_urls\')||\'[]\');'
                f'if(!u.includes(\'{safe_url}\'))u.push(\'{safe_url}\');'
                f'localStorage.setItem(\'marinos_read_urls\',JSON.stringify(u));" '
                f'style="display:inline-block;padding:5px 12px;font-size:0.85em;'
                f'border:1px solid #888;border-radius:5px;text-decoration:none;color:#444;">'
                f'記事を読む →</a>',
                unsafe_allow_html=True,
            )

        with col_check:
            checked = st.checkbox("既読", key=f"cb_{prefix}_{i}", value=is_read)
            if checked and not is_read:
                mark_read(url)
                st.rerun()
            elif not checked and is_read:
                unmark_read(url)
                st.rerun()

        st.divider()

    if displayed == 0:
        st.info("表示する記事がありません（「既読記事も表示する」をオンにすると既読記事も表示されます）")


# ── ニュース取得 ──────────────────────────────────────────────
if fetch_button:
    if not selected:
        st.warning("カテゴリを1つ以上選択してください。")
        st.stop()

    news_frames = []
    with st.spinner("ニュースを取得中..."):
        for label in selected:
            kw = KEYWORD_MAP[label]
            df_kw = fetch_marinos_news(keyword=kw, max_items=max_items, days=days)
            news_frames.append(df_kw)

    df_news = pd.concat(news_frames, ignore_index=True)
    df_news = df_news.drop_duplicates(subset=["URL"])
    df_news = df_news.sort_values("公開日時", ascending=False, na_position="last")
    df_news = df_news.reset_index(drop=True)
    st.session_state.df_news = df_news

    df_yt = pd.DataFrame()
    if youtube_enabled:
        try:
            api_key = st.secrets.get("YOUTUBE_API_KEY", "")
        except FileNotFoundError:
            api_key = ""

        if api_key:
            yt_frames = []
            with st.spinner("YouTube動画を取得中..."):
                for label in selected:
                    kw = KEYWORD_MAP[label]
                    df_kw = fetch_youtube_videos(keyword=kw, max_items=10, days=days, api_key=api_key)
                    yt_frames.append(df_kw)
            df_yt = pd.concat(yt_frames, ignore_index=True)
            df_yt = df_yt.drop_duplicates(subset=["URL"])
            df_yt = df_yt.sort_values("公開日時", ascending=False, na_position="last")
            df_yt = df_yt.reset_index(drop=True)
        else:
            st.warning("YouTube APIキーが設定されていません")
    st.session_state.df_yt = df_yt

# ── 表示 ────────────────────────────────────────────────────
if "df_news" in st.session_state:
    st.subheader("📰 ニュース")
    if st.session_state.df_news.empty:
        st.warning("ニュースが見つかりませんでした。")
    else:
        st.success(f"{len(st.session_state.df_news)} 件のニュースを取得しました")
        render_articles(st.session_state.df_news, prefix="news")

    if youtube_enabled and "df_yt" in st.session_state and not st.session_state.df_yt.empty:
        st.subheader("▶️ YouTube 動画")
        st.success(f"{len(st.session_state.df_yt)} 件の動画を取得しました")
        render_articles(st.session_state.df_yt, prefix="yt")
else:
    st.info("左のサイドバーにある「ニュースを取得する」ボタンを押してください。")
