#!/usr/bin/env python3
"""Gemini API接続テスト"""
import os
import warnings
warnings.filterwarnings("ignore")
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from google import genai

api_key = os.getenv("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key)

print("利用可能なモデル一覧:")
try:
    for m in client.models.list():
        print(f"  {m.name}")
except Exception as e:
    print(f"❌ モデル一覧取得失敗: {e}")

print("\n簡単なテスト:")
try:
    resp = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="テスト",
    )
    print(f"✅ 成功: {resp.text.strip()}")
except Exception as e:
    err = str(e)
    if "limit: 0" in err:
        print("❌ 無料枠 limit:0 — このプロジェクト/アカウントでは無料枠が無効です")
    else:
        print(f"❌ {err[:200]}")
