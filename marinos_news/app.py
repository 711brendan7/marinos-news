import streamlit as st
import pandas as pd
from news_fetcher import fetch_marinos_news
from youtube_fetcher import fetch_youtube_videos

st.set_page_config(
    page_title="横浜F・マリノス ニュース",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ 横浜F・マリノス 最新ニュース")
st.caption("Google ニュース・スポニチ・日刊スポーツ・YouTube の情報を取得しています")

with st.sidebar:
    st.header("設定")
    keyword = st.text_input("検索キーワード", value="マリノス")
    max_items = st.slider("最大取得件数", min_value=5, max_value=50, value=20, step=5)
    days = st.slider("過去N日以内", min_value=1, max_value=30, value=3, step=1)
    youtube_enabled = st.checkbox("YouTube動画も取得する", value=True)
    fetch_button = st.button("ニュースを取得する", type="primary")


def render_table(df: pd.DataFrame):
    df_display = df.copy()
    df_display["タイトル"] = df_display.apply(
        lambda row: f'<a href="{row["URL"]}" target="_blank">{row["タイトル"]}</a>',
        axis=1,
    )
    df_display = df_display.rename(columns={"要約": "記事"})
    df_display = df_display[["タイトル", "記事", "配信元", "公開日時"]]
    st.write(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)


if fetch_button:
    # ニュース取得
    with st.spinner("ニュースを取得中..."):
        df_news = fetch_marinos_news(keyword=keyword, max_items=max_items, days=days)

    # YouTube取得
    df_yt = pd.DataFrame()
    if youtube_enabled:
        try:
            api_key = st.secrets.get("YOUTUBE_API_KEY", "")
        except FileNotFoundError:
            api_key = ""
        if api_key:
            with st.spinner("YouTube動画を取得中..."):
                df_yt = fetch_youtube_videos(
                    keyword=keyword, max_items=10, days=days, api_key=api_key
                )
        else:
            st.warning("YouTube APIキーが設定されていません（Streamlit Secrets に YOUTUBE_API_KEY を追加してください）")

    # ニュース表示
    st.subheader("📰 ニュース")
    if df_news.empty:
        st.warning("ニュースが見つかりませんでした。キーワードを変えて試してください。")
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
