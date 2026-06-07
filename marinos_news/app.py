import streamlit as st
import pandas as pd
from news_fetcher import fetch_marinos_news
from youtube_fetcher import fetch_youtube_videos

st.set_page_config(
    page_title="サッカー 最新ニュース",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ サッカー 最新ニュース")
st.caption("Google ニュース・スポニチ・日刊スポーツ・YouTube の情報を取得しています")

st.markdown("""
<style>
a.article-link {
    display: block;
    text-decoration: none;
    color: inherit;
    padding: 6px 2px;
    font-size: 0.9em;
    line-height: 1.4;
}
a.article-link:visited { color: #aaa; }
.article-meta { font-size: 0.78em; color: #999; }
a.article-link:visited .article-meta { color: #bbb; }
</style>
""", unsafe_allow_html=True)

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


def render_articles(df: pd.DataFrame):
    for i, row in df.iterrows():
        url = row["URL"]
        st.markdown(
            f'<a class="article-link" href="{url}" target="_blank" rel="noopener noreferrer">'
            f'{row["要約"]}<br>'
            f'<span class="article-meta">{row["配信元"]} ｜ {row["公開日時"]}</span></a>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<hr style="margin:2px 0;border:none;border-top:1px solid #e0e0e0;">',
            unsafe_allow_html=True,
        )


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
        render_articles(st.session_state.df_news)

    if youtube_enabled and "df_yt" in st.session_state and not st.session_state.df_yt.empty:
        st.subheader("▶️ YouTube 動画")
        st.success(f"{len(st.session_state.df_yt)} 件の動画を取得しました")
        render_articles(st.session_state.df_yt)
else:
    st.info("左のサイドバーにある「ニュースを取得する」ボタンを押してください。")
