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

# ── 既読状態の初期化 ──────────────────────────────────────────
if "read_urls" not in st.session_state:
    st.session_state.read_urls = set()
if "read_urls_loaded" not in st.session_state:
    st.session_state.read_urls_loaded = False
if "read_urls_dirty" not in st.session_state:
    st.session_state.read_urls_dirty = False

# localStorage から既読URLを初回のみ読み込む
if not st.session_state.read_urls_loaded:
    raw = st_javascript(
        "JSON.parse(localStorage.getItem('marinos_read_urls') || '[]')",
        key="ls_read",
    )
    if isinstance(raw, list):
        st.session_state.read_urls = set(raw)
        st.session_state.read_urls_loaded = True

# 変更があったときだけ localStorage に保存（余分な再描画を防ぐ）
if st.session_state.read_urls_dirty:
    urls_json = json.dumps(list(st.session_state.read_urls))
    st_javascript(
        f"localStorage.setItem('marinos_read_urls', JSON.stringify({urls_json}))",
        key="ls_write",
    )
    st.session_state.read_urls_dirty = False


def mark_read(url: str):
    st.session_state.read_urls.add(url)
    st.session_state.read_urls_dirty = True


def unmark_read(url: str):
    st.session_state.read_urls.discard(url)
    st.session_state.read_urls_dirty = True


# ── サイドバー ────────────────────────────────────────────────
with st.sidebar:
    st.header("設定")

    fetch_button = st.button("ニュースを取得する", type="primary", use_container_width=True)

    st.subheader("カテゴリ")
    chk_marinos = st.checkbox("横浜F・マリノス", value=True)
    chk_japan   = st.checkbox("サッカー日本代表", value=False)
    chk_maeda   = st.checkbox("前田大然", value=False)
    custom_keyword = st.text_input("カスタムキーワード（任意）", value="", placeholder="例：久保建英")

    st.subheader("オプション")
    max_items = st.slider("最大取得件数（カテゴリごと）", min_value=5, max_value=50, value=20, step=5)
    days = st.slider("過去N日以内", min_value=1, max_value=30, value=3, step=1)
    youtube_enabled = st.checkbox("YouTube動画も取得する", value=True)
    show_read = st.checkbox("既読記事を隠す", value=False)

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

        if is_read and show_read:
            continue

        displayed += 1
        col_text, col_action = st.columns([7, 2])

        with col_action:
            if is_read:
                if st.button("✅ 既読", key=f"unread_{prefix}_{i}"):
                    unmark_read(url)
                    st.rerun()
                st.markdown(
                    f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                    f'style="display:inline-block;margin-top:4px;padding:5px 10px;'
                    f'font-size:0.85em;border:1px solid #4caf50;border-radius:5px;'
                    f'text-decoration:none;color:#4caf50;">→ 記事を開く</a>',
                    unsafe_allow_html=True,
                )
            else:
                if st.button("📖 読む", key=f"read_{prefix}_{i}"):
                    mark_read(url)
                    st.rerun()

        with col_text:
            if is_read:
                st.markdown(
                    f'✅ <span style="color:#aaa;">{row["要約"]}</span>',
                    unsafe_allow_html=True,
                )
            else:
                st.write(row["要約"])
            st.caption(f'{row["配信元"]} ｜ {row["公開日時"]}')

        st.divider()

    if displayed == 0:
        st.info("表示する記事がありません（「既読記事を隠す」をオフにすると既読記事も表示されます）")


# ── ニュース取得 ──────────────────────────────────────────────
if fetch_button:
    if not selected:
        st.warning("カテゴリを1つ以上選択してください。")
        st.stop()

    news_frames = []
    with st.spinner("ニュースを取得中..."):
        for label in selected:
            df_kw = fetch_marinos_news(keyword=KEYWORD_MAP[label], max_items=max_items, days=days)
            news_frames.append(df_kw)

    df_news = pd.concat(news_frames, ignore_index=True)
    df_news = df_news.drop_duplicates(subset=["URL"])
    df_news = df_news.sort_values("公開日時", ascending=False, na_position="last")
    st.session_state.df_news = df_news.reset_index(drop=True)

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
                    df_kw = fetch_youtube_videos(keyword=KEYWORD_MAP[label], max_items=10, days=days, api_key=api_key)
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
