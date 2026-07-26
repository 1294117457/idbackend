#!/usr/bin/env python3
"""测试 LLM API 连接"""

import os
import sys

# 添加 backend 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.infra.config import get_llm_config
from langchain_openai import ChatOpenAI


def test_llm_connection():
    cfg = get_llm_config()
    print("=" * 50)
    print("LLM 配置:")
    for k, v in cfg.items():
        if k == "api_key":
            v = f"{v[:10]}...{v[-4:]}" if len(v) > 20 else v
        print(f"  {k}: {v}")
    print("=" * 50)

    try:
        llm = ChatOpenAI(
            model=cfg.get("chat_model", "gpt-4o"),
            api_key=cfg.get("api_key") or "",
            base_url=cfg.get("base_url"),
            temperature=0.7,
            timeout=30.0,
        )

        # 测试非流式调用
        print("\n测试 LLM 调用 (同步)...")
        messages = [
            {"role": "user", "content": "你好，请回复'测试成功'"}
        ]
        response = llm.invoke(messages)
        print(f"响应: {response.content}")
        print("✅ LLM 调用成功!")

    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_llm_connection()
