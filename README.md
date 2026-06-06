# 横浜F・マリノス ニュース収集アプリ

Google ニュース RSS から横浜F・マリノスの最新ニュースを取得して一覧表示する Web アプリです。

---

## フォルダ構成

```
test-project/
├── marinos_news/
│   ├── app.py            # Streamlit の画面（メインファイル）
│   ├── news_fetcher.py   # ニュース取得の処理
│   └── requirements.txt  # 必要なライブラリ一覧
└── README.md             # このファイル
```

---

## 必要なもの

- Python 3.10 以上
- VS Code（Mac）

---

## セットアップ手順（初回のみ）

### 1. ターミナルを開く

VS Code の上部メニュー → **「ターミナル」→「新しいターミナル」**

### 2. フォルダに移動する

```bash
cd ~/test-project/marinos_news
```

### 3. 仮想環境を作る（推奨）

```bash
python3 -m venv venv
source venv/bin/activate
```

> ターミナルの先頭に `(venv)` と表示されれば成功です。

### 4. ライブラリをインストールする

```bash
pip install -r requirements.txt
```

---

## 起動方法

```bash
cd ~/test-project/marinos_news
source venv/bin/activate   # ← 仮想環境を使う場合
streamlit run app.py
```

ブラウザが自動で開き、アプリが表示されます。  
（自動で開かない場合は `http://localhost:8501` をブラウザで開いてください）

---

## 使い方

1. 画面左の **サイドバー** でキーワードと取得件数を設定する
2. **「ニュースを取得する」** ボタンを押す
3. ニュース一覧が表示される（タイトルをクリックで記事を開けます）

---

## 今後の拡張予定

- [ ] Google スプレッドシートへの自動保存
- [ ] LINE Notify による新着通知
