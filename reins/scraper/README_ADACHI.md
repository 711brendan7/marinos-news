# 足立区の独立巡回・LINEグループ通知

三浦とは別系統で足立区の売買物件を巡回し、新着を **LINEグループ** に通知する仕組み。

## 構成
- **独立系統**: `run_adachi.sh` が `REINS_CONDITION=足立区 REINS_CONDITIONS=足立` でスクレイパーを走らせる。
  三浦とは別スプレッドシート・別Driveフォルダ・別キャッシュキー（`_spreadsheet_足立区` 等）になる。
  仕入れスコアラーは通さない（スコア無しの生「🏠 REINS新着（足立区）」通知のみ）。
- **実行タイミング**: `run_pipeline.sh` の末尾に組み込み済み。既存 launchd（`com.reins.scraper`・毎日8/12/16時）と
  スマホ「今すぐ巡回」の両方で、三浦の後に順次実行される（REINSログイン衝突を避けるため直列）。
- **通知先**: `.env` の `LINE_TO_ADACHI`（LINEグループID・`C` で始まる）。
  **未設定の間は自分（`LINE_USER_ID`）へフォールバック**するので、先に動かして後からグループIDを入れてよい。
- REINS 側に保存条件「足立区」（ワンタッチ検索）が存在することが前提（キーワード「足立」で該当条件にマッチ）。

## LINEグループIDの取得手順
push 送信自体に Webhook は不要だが、**グループIDを知るには一度だけ Webhook でイベントを受ける**必要がある。

1. **LINE Developers コンソール**（Messaging APIチャンネル）→「Messaging API設定」で
   - 「グループトーク・複数人トークへの参加を許可する」を **ON**
   - 「Webhookの利用」を **ON**
2. 一時的な受信先として **https://webhook.site** を開き、発行された自分専用URLをコピー。
   これを LINE の **Webhook URL** に貼って保存。
3. **LINEグループを作成**し、通知したい人を招待。さらに**このボット（公式アカウント）もグループに招待**する。
4. グループで誰かがメッセージを送る（またはボット参加時のイベントが飛ぶ）。
   webhook.site に届いた JSON の `events[0].source.groupId`（`C` で始まる文字列）をコピー。
5. `.env` の `LINE_TO_ADACHI=Cxxxxxxxx...` に貼る。
6. （任意）Webhook URL は空に戻してよい。push 送信は Webhook 不要。

## 動作確認
```bash
cd /Users/masato/test-project/reins/scraper
./run_adachi.sh          # 足立区だけを1回巡回（ブラウザが開く・2〜4分）
```
- 初回は足立区の専用スプレッドシートを新規作成し、**その時点の全物件を新着として通知**する（以降は差分のみ）。
- `LINE_TO_ADACHI` が未設定なら通知は自分に届く。設定済みならグループに届く。

## 新着のみ・毎回全件巡回しない設計（重要）
`run_adachi.sh` は以下の env を渡し、「新着だけ通知・既知は無駄に触らない」を実現している：
- `REINS_SPREADSHEET_URL=<.env の REINS_SPREADSHEET_URL_ADACHI>`：**シートを固定**。巡回ごとに作り直さない＝新規0件のとき再通知しない・PWA の merge 先とも一致し続ける。
- `REINS_DOWNLOAD_NEW_ONLY=1`：既知(`_sheet_sent_足立区`)の物件は図面DLフェーズを丸ごとスキップ。過去に「(行なし)失敗」した行を毎回リトライしないので**1〜2分で完了**（従来は全件やり直しで2時間級）。価格/取引状況/掲載順の更新はリスト走査側で従来どおり行う。
- `REINS_NOTIFY_ONLY_NEW=1`：新規0件のときは「確認完了（新着なし）」の ping も送らない＝**本当に新着があるときだけ通知**。

**cache.json はアトミック保存**（`.tmp`→`os.replace`、直前の正本を `.bak` に退避）。load は壊れていたら `.bak` にフォールバック。これで「途中終了→cache破損→空扱い→シート再作成＋全件再通知」の事故を防ぐ（この事故が2026-08-30に発生し、足立区シートが `1-RDVEKGX…`→`1ojob…` に作り直され296件が再通知された。対策済み）。

固定シート: `1ojob_Y8MyAnZ7OV0ySbcsC1FvNkHOqiIJLsD-FqEEzU`（旧 `1-RDVEKGX…` は孤児。削除可）。

## 注意
- 足立区は独立スプレッドシートのため、既存 PWA（`docs/reins.html`・三浦シート）には**表示されない**。
  スマホでも足立区を見たい場合は PWA 側の対応が別途必要（未実装）。
- `LINE_TO`（汎用の宛先上書き）と `LINE_TO_ADACHI`（足立区専用）は別物。三浦の通知先は従来どおり `LINE_USER_ID`。
