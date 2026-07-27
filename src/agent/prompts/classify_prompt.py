"""意图分类 Prompt"""

INTENT_CLASSIFY_PROMPT = """你是一个意图分类助手。

可用意图：
- chat: 用户在闲聊、问候、寒暄、或日常对话

判断规则：
- 问候、寒暄、日常对话、无具体业务诉求 → chat

用户消息：{content}

请只返回一个词：chat
"""