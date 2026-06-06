import streamlit as st
from news_fetcher import fetch_marinos_news, fetch_article_summary

# ---- ページ設定 ----
st.set_page_config(
    page_title="横浜F・マリノス ニュース",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ 横浜F・マリノス 最新ニュース")
st.caption("Google ニュース RSS から取得しています")

# ---- サイドバー設定 ----
with st.sidebar:
    st.header("設定")
    keyword = st.text_input("検索キーワード", value="マリノス")
    max_items = st.slider("最大取得件数", min_value=5, max_value=50, value=20, step=5)
    fetch_button = st.button("ニュースを取得する", type="primary")

# ---- ニュース取得・表示 ----
if fetch_button:
    with st.spinner("ニュースを取得中..."):
        df = fetch_marinos_news(keyword=keyword, max_items=max_items)

    if df.empty:
        st.warning("ニュースが見つかりませんでした。キーワードを変えて試してください。")
    else:
        st.success(f"{len(df)} 件のニュースを取得しました")

        # Claude API で各記事の要約を生成
        try:
            api_key = st.secrets["ANTHROPIC_API_KEY"]
        except Exception:
            api_key = ""

        if api_key:
            progress = st.progress(0, text="Claude AIで要約を生成中...")
            summaries = []
            for i, title in enumerate(df["タイトル"]):
                summaries.append(fetch_article_summary(title, api_key=api_key))
                progress.progress((i + 1) / len(df), text=f"要約を生成中... ({i + 1}/{len(df)})")
            progress.empty()
        else:
            st.warning("⚠️ ANTHROPIC_API_KEY が未設定です。Streamlit Cloud の Secrets に登録してください。")
            summaries = [""] * len(df)
        df["要約"] = summaries

        # タイトルをリンク付きで表示するために列を加工
        df_display = df.copy()
        df_display["タイトル"] = df_display.apply(
            lambda row: f'<a href="{row["URL"]}" target="_blank">{row["タイトル"]}</a>',
            axis=1,
        )

        # URL列は非表示（タイトルにリンクを埋め込んだので不要）
        df_display = df_display[["タイトル", "要約", "配信元", "公開日時"]]

        st.write(
            df_display.to_html(escape=False, index=False),
            unsafe_allow_html=True,
        )

        # --- 将来の拡張用コメント ---
        # TODO: Googleスプレッドシートへの保存
        # TODO: LINE通知

else:
    st.info("左のサイドバーにある「ニュースを取得する」ボタンを押してください。")
