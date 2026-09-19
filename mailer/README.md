# 一斉メール営業基盤（不動産会社向け）

不動産会社（約4,700社）へ物件仕入れPRの一斉メールを送る。独自ドメイン brendan711.com
から Google Workspace + Brevo 経由で認証送信し、1都3県に絞って1日ぶんずつウォームアップ配信する。

## パイプライン

1. `make_lists.py` — BlastMailのエクスポートCSVをクリーニングし、`out/batches/batch_NN.csv`
   へバッチ分割する
2. `brevo_send.py setup` — フォルダ・バッチ別リスト作成・連絡先取込（初回一度だけ）
3. `brevo_send.py`（日次） — Brevo API で1日ぶんのバッチを自動送信。`.env` に `BREVO_API_KEY` 等
   を設定（`.env.example` 参照）
4. `com.brendan.mailer.plist` — launchd 定期実行の設定

## 運用ルール

- エラー停止・配信停止（unsubscribe/bounce）になったアドレスへの再送は禁止
- `email_body.txt` が送信本文のテンプレート
- 張り付き・自動回収については [project_bulk_mail_suspension] 参照（別リポジトリ運用の場合あり）

## 既知の改善候補

- `brevo_send.py` の API 呼び出しは一時的なネットワークエラーでも即座に停止するため、
  リトライ処理の追加を検討中
- `.env` 読み込みが自前パーサー実装（他プロジェクトは `python-dotenv` を使用）
