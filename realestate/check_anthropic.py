#!/usr/bin/env python3
import os, warnings
warnings.filterwarnings("ignore")
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
try:
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=64,
        messages=[{"role": "user", "content": "「テスト成功」とだけ返答してください"}],
    )
    print(f"✅ 接続成功: {msg.content[0].text.strip()}")
except Exception as e:
    print(f"❌ エラー: {e}")
