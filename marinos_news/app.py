import json
import os
import anthropic
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from news_fetcher import fetch_marinos_news
from youtube_fetcher import fetch_youtube_videos

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")

CATEGORY_COLORS = [
    "#E74C3C", "#3498DB", "#2ECC71", "#F39C12",
    "#9B59B6", "#1ABC9C", "#E67E22", "#607D8B",
]

DEFAULT_CATEGORIES = ["横浜F・マリノス", "サッカー日本代表", "前田大然", "Jリーグ移籍"]
DEFAULT_KEYWORD_MAP = {
    "横浜F・マリノス": "マリノス",
    "サッカー日本代表": "サッカー日本代表",
    "前田大然": "前田大然",
    "Jリーグ移籍": "Jリーグ移籍",
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


st.set_page_config(
    page_title="サッカー 最新ニュース",
    page_icon="⚽",
    layout="wide",
)

# ── PIN認証 ───────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown('<p style="font-size:1.2em;font-weight:700;margin:0 0 4px;">⚽ 最新ニュース</p>', unsafe_allow_html=True)
    pin_input = st.text_input("PINコードを入力してください", type="password", max_chars=8)
    if st.button("ログイン", type="primary"):
        correct_pin = st.secrets.get("APP_PIN", "")
        if pin_input == correct_pin:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("PINコードが正しくありません")
    st.stop()

# ── 永続設定の読み込み（セッション初回のみ） ──────────────────
if "settings_loaded" not in st.session_state:
    saved = load_settings()
    st.session_state.categories = saved.get("categories", DEFAULT_CATEGORIES.copy())
    st.session_state.keyword_map = {**DEFAULT_KEYWORD_MAP, **saved.get("keyword_map", {})}
    st.session_state.settings_loaded = True

for cat in st.session_state.categories:
    if cat not in st.session_state.keyword_map:
        st.session_state.keyword_map[cat] = cat


def get_cat_color(cat: str) -> str:
    cats = st.session_state.categories
    idx = cats.index(cat) if cat in cats else 0
    return CATEGORY_COLORS[idx % len(CATEGORY_COLORS)]


st.markdown('<p style="font-size:1.2em;font-weight:700;margin:0 0 4px;">⚽ 最新ニュース</p>', unsafe_allow_html=True)
st.caption("Google ニュース・Yahoo!ニュース・スポニチ・日刊スポーツ・YouTube の情報を取得しています")

st.components.v1.html("""
<script>
(function() {
  var head = window.parent.document.head;
  function addTag(tag, attrs) {
    var el = window.parent.document.createElement(tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    head.appendChild(el);
  }
  if (!window.parent.document.querySelector("link[rel='apple-touch-icon']")) {
    addTag('link', { rel: 'apple-touch-icon', href: 'app/static/icon.svg' });
  }
  if (!window.parent.document.querySelector("link[rel='manifest']")) {
    addTag('link', { rel: 'manifest', href: 'app/static/manifest.json' });
  }
})();
</script>
""", height=0)

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
.cat-badge {
    display: inline-block;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 0.68em;
    font-weight: bold;
    color: #fff;
    margin-right: 4px;
    vertical-align: middle;
}
</style>
""", unsafe_allow_html=True)

# ── サイドバー ────────────────────────────────────────────────
with st.sidebar:
    st.header("設定")

    fetch_button = st.button("ニュースを取得する", type="primary", use_container_width=True)

    st.subheader("カテゴリ")

    cat_mode = st.radio("絞り込みモード", ["OR", "AND"], horizontal=True)
    use_and = (cat_mode == "AND")

    for cat in st.session_state.categories:
        if f"cat_{cat}" not in st.session_state:
            st.session_state[f"cat_{cat}"] = True

    col_all, col_none = st.columns(2)
    with col_all:
        if st.button("全選択", use_container_width=True):
            for cat in st.session_state.categories:
                st.session_state[f"cat_{cat}"] = True
            st.rerun()
    with col_none:
        if st.button("全解除", use_container_width=True):
            for cat in st.session_state.categories:
                st.session_state[f"cat_{cat}"] = False
            st.rerun()

    selected = []
    for cat in st.session_state.categories:
        color = get_cat_color(cat)
        col_dot, col_chk = st.columns([1, 8])
        with col_dot:
            st.markdown(
                f'<div style="width:10px;height:10px;border-radius:2px;'
                f'background:{color};margin-top:10px;"></div>',
                unsafe_allow_html=True,
            )
        with col_chk:
            if st.checkbox(cat, key=f"cat_{cat}"):
                selected.append(cat)

    with st.expander("カテゴリー管理"):
        with st.form("add_cat_form", clear_on_submit=True):
            new_cat = st.text_input("カテゴリ名を追加", placeholder="例：久保建英")
            if st.form_submit_button("追加") and new_cat.strip():
                name = new_cat.strip()
                if name not in st.session_state.categories:
                    st.session_state.categories.append(name)
                    st.session_state.keyword_map[name] = name
                    save_settings({
                        "categories": st.session_state.categories,
                        "keyword_map": st.session_state.keyword_map,
                    })
                st.rerun()

        st.write("削除:")
        to_delete = None
        for cat in st.session_state.categories:
            color = get_cat_color(cat)
            col_name, col_del = st.columns([5, 2])
            with col_name:
                st.markdown(
                    f'<span style="display:inline-block;width:8px;height:8px;border-radius:2px;'
                    f'background:{color};margin-right:4px;vertical-align:middle;"></span>{cat}',
                    unsafe_allow_html=True,
                )
            with col_del:
                if st.button("削除", key=f"del_{cat}", use_container_width=True):
                    to_delete = cat

        if to_delete:
            st.session_state.categories.remove(to_delete)
            st.session_state.keyword_map.pop(to_delete, None)
            save_settings({
                "categories": st.session_state.categories,
                "keyword_map": st.session_state.keyword_map,
            })
            st.rerun()

    st.subheader("オプション")
    max_items = st.slider("最大取得件数（カテゴリごと）", min_value=5, max_value=50, value=20, step=5)
    days = st.slider("過去N日以内", min_value=1, max_value=30, value=3, step=1)
    youtube_enabled = st.checkbox("YouTube動画も取得する", value=False)


def generate_overall_summary(df: pd.DataFrame) -> str:
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except FileNotFoundError:
        api_key = ""
    if not api_key:
        return ""
    titles = df["タイトル"].tolist()[:40]
    titles_text = "\n".join(f"・{t}" for t in titles)
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": (
                "以下のサッカーニュースの見出し一覧を3〜5文で日本語で要約してください。"
                "トレンドや注目の話題を中心に簡潔にまとめてください。\n\n" + titles_text
            ),
        }],
    )
    return message.content[0].text


def render_articles(df: pd.DataFrame):
    for _, row in df.iterrows():
        url = row["URL"]
        cats = row.get("カテゴリー", [])
        if not isinstance(cats, list):
            cats = []

        badges = "".join(
            f'<span class="cat-badge" style="background:{get_cat_color(c)};">{c}</span>'
            for c in cats
        )

        st.markdown(
            f'<a class="article-link" href="{url}" target="_blank" rel="noopener noreferrer">'
            f'{badges}'
            f'<span style="font-weight:600;">{row["タイトル"]}</span><br>'
            f'<span class="article-meta">{row["配信元"]} ｜ {row["公開日時"]}</span></a>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<hr style="margin:2px 0;border:none;border-top:1px solid #e0e0e0;">',
            unsafe_allow_html=True,
        )


# ── ニュース取得 ──────────────────────────────────────────────
auto_fetch = "df_news" not in st.session_state

if fetch_button or auto_fetch:
    if not selected:
        st.warning("カテゴリを1つ以上選択してください。")
        st.stop()

    per_cat: dict = {}
    with st.spinner("ニュースを取得中..."):
        for label in selected:
            kw = st.session_state.keyword_map.get(label, label)
            df_kw = fetch_marinos_news(keyword=kw, max_items=max_items, days=days)
            if not df_kw.empty:
                df_kw = df_kw.copy()
                df_kw["カテゴリー"] = [[label]] * len(df_kw)
            per_cat[label] = df_kw

    # URLごとにカテゴリーをマージ → OR/ANDフィルタ
    url_cats: dict = {}
    url_rows: dict = {}
    for label, df_kw in per_cat.items():
        for _, row in df_kw.iterrows():
            url = row["URL"]
            if url not in url_cats:
                url_cats[url] = []
                url_rows[url] = row.to_dict()
            if label not in url_cats[url]:
                url_cats[url].append(label)

    selected_set = set(selected)
    rows = []
    for url, cats in url_cats.items():
        if use_and and len(selected) > 1 and not selected_set.issubset(set(cats)):
            continue
        r = url_rows[url].copy()
        r["カテゴリー"] = cats
        rows.append(r)

    df_news = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not df_news.empty:
        df_news = df_news.sort_values("公開日時", ascending=False, na_position="last")
        df_news = df_news.reset_index(drop=True)
    st.session_state.df_news = df_news

    with st.spinner("全体要約を生成中..."):
        st.session_state.overall_summary = generate_overall_summary(st.session_state.df_news)

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
                    kw = st.session_state.keyword_map.get(label, label)
                    df_kw = fetch_youtube_videos(keyword=kw, max_items=10, days=days, api_key=api_key)
                    if not df_kw.empty:
                        df_kw = df_kw.copy()
                        df_kw["カテゴリー"] = [[label]] * len(df_kw)
                        yt_frames.append(df_kw)
            if yt_frames:
                df_yt = pd.concat(yt_frames, ignore_index=True)
                df_yt = df_yt.drop_duplicates(subset=["URL"])
                df_yt = df_yt.sort_values("公開日時", ascending=False, na_position="last")
                df_yt = df_yt.reset_index(drop=True)
        else:
            st.warning("YouTube APIキーが設定されていません")
    st.session_state.df_yt = df_yt


# ── 表示 ────────────────────────────────────────────────────
if "df_news" in st.session_state:
    if st.session_state.get("overall_summary"):
        st.markdown(
            f'<div style="'
            f'background:rgba(28,131,225,0.1);'
            f'border-left:4px solid #1C83E1;'
            f'padding:10px 14px;'
            f'border-radius:4px;'
            f'font-size:0.85em;'
            f'line-height:1.5;'
            f'margin-bottom:1rem;'
            f'">{st.session_state.overall_summary}</div>',
            unsafe_allow_html=True,
        )

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
