"""口语风格体系：把 docs/conversation-style.md 的规范提炼成 prompt 片段。

使用约定：只注入「开口说话」类的 prompt（访谈出题 / 即时聊天回复 / 克隆聊天 /
模拟社会双克隆对话）；抽取、打分、解析类 prompt 一律不注入，保证 JSON/分数契约稳定。
"""

from __future__ import annotations

# 轻量生活化对话风格（system prompt 片段），详见 docs/conversation-style.md
STYLE_GUIDE = """\
你说话必须遵守以下原则：
- 单条消息很短，一两行就够，别写小作文
- 像真人闲聊：用口语词和大白话，不书面、不排比、不上价值
- 一次只说一件事、只问一个问题
- 不用 bullet 列表、不做总结陈词
- 先接住对方的话再往下推进（先接后问、先接后说）
- 允许停顿词和轻微重复（“嗯”“说起来”“哈哈”之类，但别每句都带）
- 表情符号克制，能不用就不用
- 就算在做访谈，也要像闲聊挖故事，别像问卷"""


def speak_system(base: str) -> str:
    """为「开口说话」类 system prompt 拼接口语风格指南。"""
    return f"{base}\n\n{STYLE_GUIDE}"
