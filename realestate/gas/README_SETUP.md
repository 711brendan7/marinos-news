# 物件ウォッチ（スマホビューア）セットアップ

スクレイパーが書き込む「物件情報」シートを、スマホからどこでも閲覧できる PWA です。
todo アプリと同じ GAS バックエンド方式。スプレッドシートは非公開のまま使えます。

- ビューア本体: `docs/realestate.html`
- 公開URL: https://711brendan7.github.io/marinos-news/realestate.html
- バックエンド: `realestate/gas/Code.gs`（読み取り専用 Web App）

---

## 1. GAS Web App をデプロイ

1. https://script.google.com/ で「新しいプロジェクト」を作成
2. `realestate/gas/Code.gs` の内容を丸ごと貼り付け
   - `SPREADSHEET_ID` と `SHEET_NAME` は設定済み
   - `SECRET_TOKEN` = `WQZpZzGK4gsxUwha59j-xTcC`（ビューアで入力するトークン）
3. 「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
   - 実行するユーザー: **自分**
   - アクセスできるユーザー: **全員**
4. 初回は Google 認証（スプレッドシートへのアクセス許可）を承認
5. 発行された **ウェブアプリ URL**（`https://script.google.com/macros/s/.../exec`）を控える

> スプレッドシートは「自分」実行のGASが読むだけなので、共有設定を公開にする必要はありません。

## 2. スマホで開く

1. iPhone の Safari で https://711brendan7.github.io/marinos-news/realestate.html を開く
2. セットアップ画面で以下を入力
   - GAS デプロイ URL: 手順1で控えた `.../exec` URL
   - SECRET_TOKEN: `WQZpZzGK4gsxUwha59j-xTcC`
3. 「保存して開始」→ 物件カードが表示される
4. 共有ボタン →「ホーム画面に追加」でアプリ化

## 使い方

- 取得日時の新しい順に表示。直近3日以内の物件は **NEW** バッジ＆オレンジの縁取り
- 上部で会社フィルタ・キーワード検索
- 「物件ページを開く」で元の物件ページへ
- 「更新」ボタンで最新を再取得

## トークンを変えたいとき

`Code.gs` の `SECRET_TOKEN` を書き換えて再デプロイ → ビューアのセットアップを再入力
（ビューアの再セットアップは localStorage クリア or ブラウザのサイトデータ削除）
