#!/usr/bin/env python3
"""
note スキ周り／少量フォロー 自動化（フォロワー到達を増やすための運用ツール）

思想（publish_helper.py と同じ = 凍結リスク最小化）:
  - note は bot 行為を禁止。だから「大量・機械的」を避け、人間らしく少量・低速で動く。
  - 対象は #ボロ戸建て/#大家/#不動産投資 など “本命ニッチの新着記事だけ”。
    無差別スキではなく「本当に関連する相手」に限定 → スパムでなく自然な相互・返報率も高い。
  - 日次上限 + ウォームアップ（初日は控えめ→徐々に）。engaged/followed ログで冪等。
  - スキと同時に、同ページ上の著者を少量だけフォロー（フォロー増加の本命レバー）。

前提:
  ./venv/bin/python -m pip install playwright && ./venv/bin/python -m playwright install chromium
  ログインは初回だけ手動。プロファイル note/.note_profile を publish_helper.py と共用。
  （未ログインなら publish_helper.py を一度起動して手動ログインしておく）

使い方:
  ./venv/bin/python engage.py --dry-run        # 収集だけ。誰に何をするか一覧（ブラウザ起動なし）
  ./venv/bin/python engage.py --headful        # 実行を目視（初回はこれで挙動確認を推奨）
  ./venv/bin/python engage.py                   # 通常実行（launchd から毎日1回呼ぶ想定）
"""
from __future__ import annotations

import re
import sys
import json
import time
import random
import argparse
import datetime as dt
import urllib.parse
import urllib.request
import concurrent.futures
from pathlib import Path

# ファイル/パイプへリダイレクトすると stdout がフルバッファリングされ、
# 出力が少ない間はプロセス終了までログに何も書かれない＝「ハングしている」ように
# 見えてしまう（2026-09-07、実際は正常進行中だったのに無反応と誤認した）。
# 行バッファに強制して、print() の都度すぐ書き出す。
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# ========================= 設定 =========================
MY_URLNAME = "musyoku_ooya"          # 自分（対象から除外）

# 本命ニッチのキーワード（この著者たちに絡む＝フォロー理由が近い＝返報されやすい）
# ※検索は“著者”を広く拾うため。記事1件ずつのタイトルは下の TITLE_RELEVANT_RE で再判定する。
KEYWORDS = [
    "ボロ戸建て", "戸建て投資", "大家", "不動産投資", "賃貸経営",
    "再建築不可", "指値 不動産", "築古 アパート", "空き家 再生",
    "戸建て 大家", "区分マンション 投資", "融資 不動産",
]

# 記事タイトルがこの実務ワードを含まなければ対象外（英会話回・雑記などのノイズを弾く）
TITLE_RELEVANT_RE = re.compile(
    r"(大家|戸建|アパート|マンション|一棟|区分|RC|木造|物件|不動産|賃貸|入居|家賃|"
    r"利回り|融資|指値|リフォーム|DIY|空き家|空家|再生|再建築|市街化|客付|滞納|"
    r"管理会社|内見|重説|重要事項|残置|原状回復|登記|競売|任意売却|セミリタイア|"
    r"FIRE|サブリース|団信|収益物件|投資用|オーナー|入居者|退去)"
)

# 法人・PR・雑記を除外（表示名／urlname／タイトルで判定）
EXCLUDE_AUTHOR_RE = re.compile(
    r"(株式会社|合同会社|有限会社|㈱|（株）|\(株\)|Inc\.?|Corp\.?|LLC|Ltd\.?|"
    r"公式|オフィシャル|Official|編集部|ニュース|マガジン編集)"
)
EXCLUDE_URLNAME_RE = re.compile(
    r"(inc|corp|company|official|_pr\b|_news|_mag|_media|_press|estate_?corp)", re.I
)
EXCLUDE_TITLE_RE = re.compile(
    r"(【?PR】?|広告|プロモーション|スポンサー|おてつたび|セミナー募集|無料相談|"
    r"LINE登録|プレゼント企画|アフィリ|募集中！|"
    r"ニュース(まとめ|注目|ピック|速報|解説)?|今日のニュース|注目\d+本|"
    r"週刊|日刊|今週の|マーケット速報)"
)

AUTO_FOLLOW = False                  # 自動フォローはしない（本人指示、2026-09-07）。cold/reciprocateともスキのみ。
DAILY_LIKE_CAP = 50                  # ウォームアップ後の1日上限
DAILY_FOLLOW_CAP = 10                # AUTO_FOLLOW=False の間は使われない
WARMUP_DAYS = 7                      # 初日から7日かけて上限まで線形に増やす
LIKE_FLOOR, FOLLOW_FLOOR = 8, 3      # 初日でも最低これだけは動く

RECIPROCATE_FOLLOW_BACK = False      # 返しはスキ返しのみ。フォロー返しはしない（--follow-back で一時的に有効化）

RECENT_DAYS = 30                     # これより古い記事は対象外
MIN_FOLLOWERS, MAX_FOLLOWERS = 2, 20000   # 死にアカ/メガアカを避ける
ONE_PER_AUTHOR = True               # 1回の実行で同一著者は1記事だけ（多数の書き手に薄く広く）

# 人間らしい間隔（秒）
DELAY_MIN, DELAY_MAX = 18, 55        # アクション間
LONG_BREAK_EVERY = 7                 # N件ごとに長め休憩
LONG_BREAK_MIN, LONG_BREAK_MAX = 120, 300

BASE = Path(__file__).resolve().parent
PROFILE_DIR = BASE / ".note_profile"
ENGAGED_LOG = BASE / "engaged.log"   # スキ済み note key（1行1件）
FOLLOWED_LOG = BASE / "followed.log" # フォロー済み urlname（1行1件）
LIKEDBACK_LOG = BASE / "likedback.log"  # スキ返し済みの相手 urlname（1行1件）
STATE_FILE = BASE / "engage_state.json"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"}


# ========================= ログ／状態 =========================
def _load_set(p: Path) -> set:
    return {ln.strip() for ln in p.read_text("utf-8").splitlines() if ln.strip()} if p.exists() else set()


def _append(p: Path, val: str):
    with p.open("a", encoding="utf-8") as f:
        f.write(val + "\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text("utf-8"))
    return {"warmup_start": dt.date.today().isoformat()}


def save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1), "utf-8")


def todays_caps(state: dict) -> tuple[int, int]:
    """ウォームアップ: 開始からの経過日で上限を線形に上げる。"""
    start = dt.date.fromisoformat(state.get("warmup_start", dt.date.today().isoformat()))
    day = (dt.date.today() - start).days
    frac = min(1.0, (day + 1) / WARMUP_DAYS)
    likes = max(LIKE_FLOOR, round(DAILY_LIKE_CAP * frac))
    follows = max(FOLLOW_FLOOR, round(DAILY_FOLLOW_CAP * frac)) if AUTO_FOLLOW else 0
    return likes, follows


# ========================= 収集（read-only API）=========================
# urlopen(timeout=N) はソケットレベルのtimeoutで、DNS解決やCDN側の接続不良では
# 効かず無期限ハングすることが実際にあった（2026-09-07、discoverが15分以上停止）。
# SIGALRMでの壁時計保険も試したが、ブロッキングのC/SSL層にシグナルが届かず無力
# だったため、別スレッド+ハードjoinタイムアウトに変更。呼び出し元は必ず制御を
# 取り戻せる（下層が本当に無限ハングしても、そのスレッドを置き去りにして進む）。
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="note_api")


def _get_json(url: str, hang_timeout: float = 12.0) -> dict:
    def _fetch():
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    fut = _POOL.submit(_fetch)
    try:
        return fut.result(timeout=hang_timeout)
    except concurrent.futures.TimeoutError:
        fut.cancel()  # 実行中でも キャンセルはできないが、待つのはここで打ち切る
        raise TimeoutError(f"_get_json hung >{hang_timeout}s: {url[:80]}")


def creator_followers(urlname: str) -> int | None:
    try:
        d = _get_json(f"https://note.com/api/v2/creators/{urllib.parse.quote(urlname)}")
        return d.get("data", {}).get("followerCount")
    except Exception:
        return None


def _excluded_user(urlname: str, name: str) -> bool:
    """法人・PR・公式などは返し対象からも除外（cold と同じ基準）。"""
    return bool(EXCLUDE_AUTHOR_RE.search(name or "")
                or EXCLUDE_URLNAME_RE.search(urlname or ""))


def my_followers() -> list[dict]:
    """自分のフォロワーを新しい順で全取得。urlname/name/followerCount/hasPublishedNote。"""
    out, page = [], 1
    while page <= 50:  # 上限ガード
        try:
            d = _get_json(f"https://note.com/api/v2/creators/{MY_URLNAME}/followers?page={page}")["data"]
        except Exception:
            break
        for u in d.get("follows", []):
            if u.get("withdrawal"):
                continue
            out.append({"urlname": u.get("urlname", ""),
                        "name": u.get("nickname") or u.get("name") or "",
                        "followers": u.get("followerCount"),
                        "has_note": bool(u.get("hasPublishedNote", True))})
        if d.get("isLastPage") or not d.get("follows"):
            break
        page += 1
        time.sleep(0.3)
    return out


def my_likers() -> list[dict]:
    """自分の記事にスキしてくれた人を集約（重複除去・多くスキした人ほど前）。"""
    counts, info = {}, {}
    keys, page = [], 1
    while page <= 10:
        try:
            d = _get_json(f"https://note.com/api/v2/creators/{MY_URLNAME}/contents?kind=note&page={page}")["data"]
        except Exception:
            break
        keys += [n["key"] for n in d.get("contents", [])]
        if d.get("isLastPage"):
            break
        page += 1
        time.sleep(0.2)
    for k in keys:
        try:
            d = _get_json(f"https://note.com/api/v3/notes/{k}/likes")["data"]
        except Exception:
            continue
        for lk in d.get("likes", []):
            u = lk.get("user") or lk
            un = u.get("urlname")
            if not un or un == MY_URLNAME:
                continue
            counts[un] = counts.get(un, 0) + 1
            info[un] = u.get("nickname") or u.get("name") or ""
        time.sleep(0.15)
    order = sorted(counts, key=lambda x: counts[x], reverse=True)
    return [{"urlname": un, "name": info[un], "likes_to_me": counts[un]} for un in order]


def latest_note_url(urlname: str) -> tuple[str, str] | None:
    """相手の最新記事の (url, title)。スキ返し先。取れなければ None。"""
    try:
        d = _get_json(f"https://note.com/api/v2/creators/{urllib.parse.quote(urlname)}/contents?kind=note&page=1")["data"]
    except Exception:
        return None
    for n in d.get("contents", []):
        key = n.get("key")
        if key:
            return (f"https://note.com/{urlname}/n/{key}", n.get("name", ""))
    return None


def discover(liked_keys: set, want: int) -> list[dict]:
    """本命キーワードで新着を集め、フィルタして候補を返す。"""
    cutoff = dt.date.today() - dt.timedelta(days=RECENT_DAYS)
    seen_keys, seen_authors, cands = set(), set(), []
    kws = KEYWORDS[:]
    random.shuffle(kws)
    for kw in kws:
        q = urllib.parse.quote(kw)
        for start in (0, 10, 20):
            try:
                d = _get_json(f"https://note.com/api/v3/searches?context=note&q={q}&size=10&start={start}")
            except Exception:
                continue
            for c in d.get("data", {}).get("notes", {}).get("contents", []):
                key = c.get("key")
                user = c.get("user", {}) or {}
                author = user.get("urlname", "")
                author_name = user.get("name") or user.get("nickname") or ""
                name = c.get("name", "")
                if not key or not author:
                    continue
                if author == MY_URLNAME or key in liked_keys or key in seen_keys:
                    continue
                if ONE_PER_AUTHOR and author in seen_authors:
                    continue
                # 記事タイトルが実務に無関係 → 除外（英会話回・雑記など）
                if not TITLE_RELEVANT_RE.search(name):
                    continue
                # 法人・PR・雑記アカ → 除外
                if (EXCLUDE_AUTHOR_RE.search(author_name)
                        or EXCLUDE_URLNAME_RE.search(author)
                        or EXCLUDE_TITLE_RE.search(name)):
                    continue
                pub = (c.get("publish_at") or "")[:10]
                try:
                    if pub and dt.date.fromisoformat(pub) < cutoff:
                        continue
                except ValueError:
                    pass
                seen_keys.add(key)
                seen_authors.add(author)
                cands.append({"key": key, "author": author, "author_name": author_name,
                              "name": name, "url": f"https://note.com/{author}/n/{key}",
                              "pub": pub, "kw": kw})
            time.sleep(0.3)
    random.shuffle(cands)
    # フォロワー数フィルタ（選抜分だけ問い合わせ＝軽く）
    out = []
    for c in cands:
        if len(out) >= want:
            break
        fol = creator_followers(c["author"])
        c["followers"] = fol
        if fol is not None and not (MIN_FOLLOWERS <= fol <= MAX_FOLLOWERS):
            continue
        out.append(c)
        time.sleep(0.2)
    return out


# ========================= アクション（Playwright）=========================
def human_sleep(a=DELAY_MIN, b=DELAY_MAX):
    time.sleep(random.uniform(a, b))


def is_logged_in(page) -> bool:
    try:
        page.goto("https://note.com/", wait_until="domcontentloaded", timeout=30000)
    except Exception:
        return False
    # ヘッダに「ログイン」「会員登録」が見えたら未ログイン
    for name in ("ログイン", "会員登録"):
        try:
            if page.get_by_role("link", name=name).first.is_visible(timeout=1500):
                return False
        except Exception:
            pass
    return True


def try_like(page) -> bool:
    """スキ。既に押下済みならスキップ。押せたら True。"""
    from playwright.sync_api import TimeoutError as PWTimeout
    candidates = [
        lambda: page.get_by_role("button", name="スキ", exact=True).first,
        lambda: page.locator('button[aria-label*="スキ"]').first,
        lambda: page.locator('button:has-text("スキ")').first,
    ]
    for make in candidates:
        try:
            btn = make()
            btn.wait_for(state="visible", timeout=4000)
        except (PWTimeout, Exception):
            continue
        # 既にスキ済み判定（aria-pressed / スキ済み表記）
        try:
            pressed = btn.get_attribute("aria-pressed")
            if pressed == "true":
                return False
        except Exception:
            pass
        try:
            btn.click(timeout=4000)
            return True
        except Exception:
            continue
    return False


def try_follow(page) -> bool:
    """同ページ上の著者をフォロー。既にフォロー中なら押さない。押せたら True。"""
    from playwright.sync_api import TimeoutError as PWTimeout
    try:
        # 「フォロー中」は完全一致にしないと掴んでしまうので exact=True
        btn = page.get_by_role("button", name="フォロー", exact=True).first
        btn.wait_for(state="visible", timeout=3000)
    except (PWTimeout, Exception):
        return False
    try:
        btn.click(timeout=3000)
        return True
    except Exception:
        return False


# ========================= ブラウザ（run/reciprocate 共通）=========================
def _clear_locks():
    # 「既存のブラウザ セッションで開いています」の元凶になる残存ロックを消す
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (PROFILE_DIR / name).unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


def _new_context(p, headful):
    _clear_locks()
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=not headful,
        viewport={"width": 1280, "height": 900},
        user_agent=UA["User-Agent"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def _closed_err(e) -> bool:
    # ブラウザ/タブが落ちた系のエラーか（クラッシュ・切断）
    s = f"{type(e).__name__}: {e}".lower()
    return ("closed" in s) or ("crash" in s) or ("targetclosed" in s)


def _safe_close(ctx):
    try:
        ctx.close()
    except Exception:
        pass


def _launch_with_retry(p, headful):
    """起動はプロフィールロック等で不安定。3回まで試して (ctx, page)。全滅なら (None, None)。"""
    ctx = None
    for attempt in range(3):
        try:
            return _new_context(p, headful)
        except Exception as e:
            print(f"  ! 起動リトライ {attempt + 1}/3: {type(e).__name__}")
            if ctx:
                _safe_close(ctx)
                ctx = None
            time.sleep(3)
    return None, None


def run(dry_run: bool, headful: bool):
    state = load_state()
    liked_keys = _load_set(ENGAGED_LOG)
    followed = _load_set(FOLLOWED_LOG)
    like_cap, follow_cap = todays_caps(state)

    # 手動で1日に複数回叩いても“今日の合計”が上限を超えないようにする。
    today = dt.date.today().isoformat()
    done = state.get("history", {}).get(today, {})
    done_like, done_follow = done.get("likes", 0), done.get("follows", 0)
    like_cap = max(0, like_cap - done_like)
    follow_cap = max(0, follow_cap - done_follow)
    if not dry_run and like_cap <= 0:
        print(f"■ 本日ぶんは消化済み（今日: スキ {done_like} / フォロー {done_follow}）。"
              f"また明日実行してください。")
        return

    print(f"■ 本日の残り上限: スキ {like_cap} / フォロー {follow_cap}"
          f"（今日すでに スキ{done_like}/フォロー{done_follow} ・"
          f"ウォームアップ開始 {state.get('warmup_start')}）")
    print(f"  収集中… キーワード{len(KEYWORDS)}種")
    # 少し多めに集めてから上限まで実行（フォロー不可などの取りこぼし吸収）
    cands = discover(liked_keys, want=like_cap + 8)
    print(f"  候補 {len(cands)} 件\n")

    if dry_run:
        for i, c in enumerate(cands[:like_cap], 1):
            fol = c.get("followers")
            print(f"  {i:>2}. [{c['kw']}] fol={fol} {c['pub']} {c['author']}  {c['name'][:34]}")
            print(f"      {c['url']}")
        print("\n[dry-run] ブラウザは起動していません。実行するには --headful か引数なしで。")
        return

    from playwright.sync_api import sync_playwright

    likes_done = follows_done = 0
    with sync_playwright() as p:
        ctx, page = _launch_with_retry(p, headful)
        if page is None:
            print("✗ ブラウザ起動に失敗しました。時間をおいて再実行してください。")
            sys.exit(3)

        if not is_logged_in(page):
            print("✗ 未ログインです。publish_helper.py を一度起動して手動ログインしてください。")
            _safe_close(ctx)
            sys.exit(2)
        print("✓ ログイン確認OK\n")

        acted = 0
        relaunches = 0
        for c in cands:
            if likes_done >= like_cap:
                break
            try:
                page.goto(c["url"], wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2.5, 6.0))  # 記事を“読む”間

                liked = try_like(page)
                if liked:
                    likes_done += 1
                    _append(ENGAGED_LOG, c["key"])
                    liked_keys.add(c["key"])

                followed_now = False
                if (AUTO_FOLLOW and follows_done < follow_cap and c["author"] not in followed
                        and random.random() < 0.6):   # 全員はフォローしない（自然さ）
                    if try_follow(page):
                        follows_done += 1
                        followed_now = True
                        _append(FOLLOWED_LOG, c["author"])
                        followed.add(c["author"])
            except Exception as e:
                # ブラウザが途中で落ちたら再起動して続行（単発クラッシュで打ち切らない）
                if _closed_err(e) and relaunches < 3:
                    relaunches += 1
                    print(f"  ⟳ ブラウザ復旧 {relaunches}/3（{c['author']} で切断）")
                    _safe_close(ctx)
                    time.sleep(3)
                    try:
                        ctx, page = _new_context(p, headful)
                    except Exception:
                        print("  ✗ 再起動に失敗。中断します。")
                        break
                    continue  # この相手は飛ばして次へ（engaged.log で二度絡みは防止）
                print(f"  ✗ スキップ {c['author']}  {type(e).__name__}: {str(e)[:60]}")
                continue

            mark = ("♥" if liked else "・") + ("+F" if followed_now else "  ")
            print(f"  {mark} [{likes_done:>2}/{like_cap}] {c['author']}  {c['name'][:30]}")

            acted += 1
            if acted % LONG_BREAK_EVERY == 0:
                time.sleep(random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX))
            else:
                human_sleep()

        # 記録は close の前に保存（close が例外でも消化数を失わない＝日次上限を守る）
        hist = state.setdefault("history", {})
        h = hist.setdefault(today, {"likes": 0, "follows": 0})
        h["likes"] += likes_done
        h["follows"] += follows_done
        save_state(state)

        # ブラウザ終了は best-effort。既に閉じていても記録は保存済みなので握り潰す。
        try:
            ctx.close()
        except Exception:
            pass

    print(f"\n■ 完了: スキ {likes_done} / フォロー {follows_done}"
          f"（本日累計 スキ{h['likes']}/フォロー{h['follows']}）")


def reciprocate(dry_run: bool, headful: bool, cap_likes=None, cap_follows=None,
                do_follow_back=None):
    """自分にスキ／フォローしてくれた人へ返す（フォロー返し・スキ返し）。
    cold と同じ日次上限・ウォームアップ・人間らしい間隔を共有し、warm を優先消化する。
    cap_likes/cap_follows を渡すと、その回だけ日次上限を無視して指定数を上限にする
    （少量の一回限り返しに使う。消化数は履歴に記録するので以後の会計は正確なまま）。
    do_follow_back は既定で RECIPROCATE_FOLLOW_BACK（=False＝フォロー返しはしない）。"""
    if do_follow_back is None:
        do_follow_back = RECIPROCATE_FOLLOW_BACK

    state = load_state()
    followed = _load_set(FOLLOWED_LOG)
    liked_back = _load_set(LIKEDBACK_LOG)
    like_cap, follow_cap = todays_caps(state)

    today = dt.date.today().isoformat()
    done = state.get("history", {}).get(today, {})
    done_like, done_follow = done.get("likes", 0), done.get("follows", 0)
    like_cap = max(0, like_cap - done_like)
    follow_cap = max(0, follow_cap - done_follow)

    override = cap_likes is not None or cap_follows is not None
    if override:
        if cap_likes is not None:
            like_cap = cap_likes
        if cap_follows is not None:
            follow_cap = cap_follows

    if not do_follow_back:
        follow_cap = 0  # フォロー返しは行わない設定（override より優先）

    if override:
        print(f"■ 一回限りの返し上限（override）: スキ {like_cap} / フォロー {follow_cap}"
              f"（本日すでに スキ{done_like}/フォロー{done_follow} 消化・"
              f"ウォームアップ開始 {state.get('warmup_start')}）")
    else:
        print(f"■ 本日の残り上限: スキ {like_cap} / フォロー {follow_cap}"
              f"（今日すでに スキ{done_like}/フォロー{done_follow} ・"
              f"ウォームアップ開始 {state.get('warmup_start')}）")
    if not do_follow_back:
        print("  ※ フォロー返しは無効（スキ返しのみ）。--follow-back で一時的に有効化")
    print("  収集中… " + ("フォロワー一覧＋" if do_follow_back else "") + "自分の記事へのスキ")

    # フォロー返し対象: まだ返していないフォロワー（新しい順）※無効時は集めない
    fb = []
    if do_follow_back:
        fb = [f for f in my_followers()
              if f["urlname"] and f["urlname"] not in followed
              and f["has_note"] and not _excluded_user(f["urlname"], f["name"])]
    # スキ返し対象: まだ返していないスキ主（多くスキした人ほど前）
    lb = [u for u in my_likers()
          if u["urlname"] not in liked_back and u["urlname"] not in {MY_URLNAME}
          and not _excluded_user(u["urlname"], u["name"])]

    if do_follow_back:
        print(f"  フォロー返し待ち {len(fb)} 人 / スキ返し待ち {len(lb)} 人\n")
    else:
        print(f"  スキ返し待ち {len(lb)} 人\n")

    if dry_run:
        if do_follow_back:
            print("  ▼ フォロー返し（上限まで実行される順）")
            for f in fb[:max(follow_cap, 10)]:
                print(f"    + {f['urlname']}  {f['name'][:24]}  (fol={f['followers']})")
        print("  ▼ スキ返し（相手の最新記事にスキ）")
        for u in lb[:max(like_cap, 10)]:
            print(f"    ♥ {u['urlname']}  {u['name'][:24]}  (自分に{u['likes_to_me']}スキ)")
        print("\n[dry-run] ブラウザは起動していません。実行するには --headful か引数なしで。")
        return

    if like_cap <= 0 and follow_cap <= 0:
        print("■ 本日ぶんは消化済み。また明日実行してください。")
        return

    from playwright.sync_api import sync_playwright

    likes_done = follows_done = 0
    with sync_playwright() as p:
        ctx, page = _launch_with_retry(p, headful)
        if page is None:
            print("✗ ブラウザ起動に失敗しました。時間をおいて再実行してください。")
            sys.exit(3)
        if not is_logged_in(page):
            print("✗ 未ログインです。publish_helper.py を一度起動して手動ログインしてください。")
            _safe_close(ctx)
            sys.exit(2)
        print("✓ ログイン確認OK\n")

        acted = 0
        relaunches = [0]

        def _recover(who):
            if relaunches[0] >= 3:
                return None
            relaunches[0] += 1
            print(f"  ⟳ ブラウザ復旧 {relaunches[0]}/3（{who} で切断）")
            _safe_close(ctx)
            time.sleep(3)
            try:
                return _new_context(p, headful)
            except Exception:
                print("  ✗ 再起動に失敗。中断します。")
                return None

        def _pace():
            nonlocal acted
            acted += 1
            if acted % LONG_BREAK_EVERY == 0:
                time.sleep(random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX))
            else:
                human_sleep()

        # 1) フォロー返し（warm・最優先）
        for f in fb:
            if follows_done >= follow_cap:
                break
            un = f["urlname"]
            try:
                page.goto(f"https://note.com/{un}", wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2.0, 4.5))
                ok = try_follow(page)
            except Exception as e:
                if _closed_err(e):
                    r = _recover(un)
                    if r is None:
                        break
                    ctx, page = r
                    continue
                print(f"  ✗ スキップ {un}  {type(e).__name__}: {str(e)[:50]}")
                continue
            if ok:
                follows_done += 1
                _append(FOLLOWED_LOG, un)
                followed.add(un)
            print(f"  {'＋F' if ok else '・ '} [{follows_done:>2}/{follow_cap}] {un}  {f['name'][:24]}")
            _pace()

        # 2) スキ返し（相手の最新記事へ）
        for u in lb:
            if likes_done >= like_cap:
                break
            un = u["urlname"]
            nt = latest_note_url(un)
            if not nt:
                _append(LIKEDBACK_LOG, un)  # 記事なし＝以後スキップ
                continue
            url, title = nt
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2.5, 6.0))
                liked = try_like(page)
            except Exception as e:
                if _closed_err(e):
                    r = _recover(un)
                    if r is None:
                        break
                    ctx, page = r
                    continue
                print(f"  ✗ スキップ {un}  {type(e).__name__}: {str(e)[:50]}")
                continue
            _append(LIKEDBACK_LOG, un)  # 押せても既押しでも「返し済み」にする
            liked_back.add(un)
            if liked:
                likes_done += 1
                key = url.rsplit("/n/", 1)[-1]
                _append(ENGAGED_LOG, key)
            print(f"  {'♥ ' if liked else '・ '} [{likes_done:>2}/{like_cap}] {un}  {title[:26]}")
            _pace()

        # 記録は close の前に保存（消化数を失わない＝日次上限を守る）
        hist = state.setdefault("history", {})
        h = hist.setdefault(today, {"likes": 0, "follows": 0})
        h["likes"] += likes_done
        h["follows"] += follows_done
        save_state(state)
        _safe_close(ctx)

    print(f"\n■ 完了（返し）: スキ返し {likes_done} / フォロー返し {follows_done}"
          f"（本日累計 スキ{h['likes']}/フォロー{h['follows']}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="収集のみ。ブラウザ起動なし")
    ap.add_argument("--headful", action="store_true", help="ブラウザを表示して実行")
    ap.add_argument("--reciprocate", action="store_true",
                    help="スキ／フォローしてくれた人へ返す（フォロー返し・スキ返し）")
    ap.add_argument("--cap-likes", type=int, default=None,
                    help="返し専用: この回だけスキ返し上限を指定（日次上限を無視）")
    ap.add_argument("--cap-follows", type=int, default=None,
                    help="返し専用: この回だけフォロー返し上限を指定（日次上限を無視）")
    ap.add_argument("--follow-back", action="store_true",
                    help="返し専用: フォロー返しも行う（既定はスキ返しのみ）")
    args = ap.parse_args()
    if args.reciprocate:
        reciprocate(dry_run=args.dry_run, headful=args.headful,
                    cap_likes=args.cap_likes, cap_follows=args.cap_follows,
                    do_follow_back=True if args.follow_back else None)
    else:
        run(dry_run=args.dry_run, headful=args.headful)


if __name__ == "__main__":
    main()
