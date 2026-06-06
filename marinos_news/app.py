import streamlit as st
from news_fetcher import fetch_marinos_news

st.set_page_config(
    page_title="横浜F・マリノス ニュース",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ 横浜F・マリノス 最新ニュース")
st.caption("Google ニュース・スポニチ・日刊スポーツ の RSS から取得しています")

with st.sidebar:
    st.header("設定")
    keyword = st.text_input("検索キーワード", value="マリノス")
    max_items = st.slider("最大取得件数", min_value=5, max_value=50, value=20, step=5)
    days = st.slider("過去N日以内", min_value=1, max_value=30, value=3, step=1)
    fetch_button = st.button("ニュースを取得する", type="primary")

if fetch_button:
    with st.spinner("ニュースを取得中..."):
        df = fetch_marinos_news(keyword=keyword, max_items=max_items, days=days)

    if df.empty:
        st.warning("ニュースが見つかりませんでした。キーワードを変えて試してください。")
    else:
        st.success(f"{len(df)} 件のニュースを取得しました")

        df_display = df.copy()
        df_display["タイトル"] = df_display.apply(
            lambda row: f'<a href="{row["URL"]}" target="_blank">{row["タイトル"]}</a>',
            axis=1,
        )
        df_display = df_display.rename(columns={"要約": "記事"})
        df_display = df_display[["タイトル", "記事", "配信元", "公開日時"]]

        st.write(
            df_display.to_html(escape=False, index=False),
            unsafe_allow_html=True,
        )
else:
    st.info("左のサイドバーにある「ニュースを取得する」ボタンを押してください。")
