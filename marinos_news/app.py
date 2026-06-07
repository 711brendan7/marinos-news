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

with st.sidebar:
    st.header("設定")

    st.subheader("カテゴリ")
    chk_marinos = st.checkbox("横浜F・マリノス", value=True)
    chk_japan   = st.checkbox("サッカー日本代表", value=False)
    chk_maeda   = st.checkbox("前田大然", value=False)

    st.subheader("オプション")
    max_items = st.slider("最大取得件数（カテゴリごと）", min_value=5, max_value=50, value=20, step=5)
    days = st.slider("過去N日以内", min_value=1, max_value=30, value=3, step=1)
    youtube_enabled = st.checkbox("YouTube動画も取得する", value=True)

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


def render_table(df: pd.DataFrame):
    df_display = df.copy()
    df_display["記事"] = df_display.apply(
        lambda row: (
            f'{row["要約"]}&nbsp;&nbsp;'
            f'<a href="{row["URL"]}" target="_blank" '
            f'style="display:inline-block;padding:2px 8px;font-size:0.75em;'
            f'border:1px solid #888;border-radius:4px;text-decoration:none;color:#444;">'
            f'記事を読む →</a>'
        ),
        axis=1,
    )
    df_display = df_display[["記事", "配信元", "公開日時"]]
    st.write(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)


if fetch_button:
    if not selected:
        st.warning("カテゴリを1つ以上選択してください。")
        st.stop()

    # ニュース取得（カテゴリごと）
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

    # YouTube取得（カテゴリごと）
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
            st.warning("YouTube APIキーが設定されていません（Streamlit Secrets に YOUTUBE_API_KEY を追加してください）")

    # ニュース表示
    st.subheader("📰 ニュース")
    if df_news.empty:
        st.warning("ニュースが見つかりませんでした。")
    else:
        st.success(f"{len(df_news)} 件のニュースを取得しました")
        render_table(df_news)

    # YouTube表示
    if youtube_enabled and not df_yt.empty:
        st.subheader("▶️ YouTube 動画")
        st.success(f"{len(df_yt)} 件の動画を取得しました")
        render_table(df_yt)

else:
    st.info("左のサイドバーにある「ニュースを取得する」ボタンを押してください。")
