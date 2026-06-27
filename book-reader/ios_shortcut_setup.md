# 読書ノート iOS ショートカット セットアップ

## 必要なもの
- GAS デプロイ済みの `BOOK_GAS_URL`
- 認証トークン `BOOK_GAS_TOKEN`

---

## ショートカット1: 「本を登録」

本の表紙を撮影して新しい本を登録する。

### アクション構成

```
1. テキストを要求
   プロンプト: 本のタイトルを入力
   → 変数 title に保存

2. テキストを要求
   プロンプト: 著者名（省略可）
   → 変数 author に保存

3. 写真を撮影（または「写真を選択」）
   → 変数 coverPhoto に保存

4. 変数を取得: coverPhoto
   → Base64 エンコード: "ベース64テキストに変換"
   → 変数 coverBase64 に保存

5. URLのコンテンツを取得
   URL: [BOOK_GAS_URL]
   メソッド: POST
   ヘッダー: Content-Type: application/json
   本文（JSON）:
   {
     "token": "[BOOK_GAS_TOKEN]",
     "action": "addBook",
     "title": [title の変数],
     "author": [author の変数],
     "coverBase64": [coverBase64 の変数],
     "coverMime": "image/jpeg"
   }

6. 辞書から値を取得: "bookId"
   → 変数 bookId に保存

7. 通知を表示
   本文: 「[title]」を登録しました（ID: [bookId]）
```

---

## ショートカット2: 「ページを撮影」

重要なページを撮影して保存＋OCR文字起こしをする。

### アクション構成

```
1. テキストを要求
   プロンプト: 本のタイトルを入力（既存の本と同じタイトルで保存されます）
   → 変数 title に保存

2. 写真を撮影（または「写真を選択」）
   → 変数 pagePhoto に保存

3. 変数を取得: pagePhoto
   → "メディアを画像に変換": JPEG、品質 0.8
   → Base64 エンコード
   → 変数 imageBase64 に保存

4. URLのコンテンツを取得
   URL: [BOOK_GAS_URL]
   メソッド: POST
   ヘッダー: Content-Type: application/json
   本文（JSON）:
   {
     "token": "[BOOK_GAS_TOKEN]",
     "action": "addPage",
     "title": [title の変数],
     "imageBase64": [imageBase64 の変数],
     "imageMime": "image/jpeg",
     "ocr": true,
     "ocrLanguage": "ja"
   }

5. 辞書から値を取得: "transcript"
   → 変数 transcript に保存

6. 通知を表示
   本文: 文字起こし: [transcript の変数]
```

---

## ヒント

- **同じ本のページ**: title を同じにすると既存の本に追加される
- **英語の本**: `"ocrLanguage": "en"` に変更
- **文字起こしが空**: GAS 側で Drive Advanced Service が有効になっているか確認
- **画像サイズ**: iPhone のカメラ写真はそのままでは大きすぎる場合がある。ショートカットの「メディアを画像に変換」ステップで幅1200px に縮小すること

## OCR の有効化（GAS 側）

GAS エディタで一度だけ手動設定が必要：

1. [script.google.com](https://script.google.com) を開く
2. プロジェクトを開く
3. 左メニュー「サービス」→「+」→「Drive API」→ バージョン v2 → 追加
4. 保存して再デプロイ
