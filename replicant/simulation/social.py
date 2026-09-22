"""复制人之间的双人对话：写回双方记忆流，并计入反思计数。

人格演进只走显式路径：对话 → 记忆 → 反思 → profile patch（新版本 + diff 原因），
不存在无声的人格漂移。
"""

from __future__ import annotations

from sqlmodel import Session

from ..db import Clone
from ..llm import LLMClient
from ..persona import memory as memory_mod
from ..style import speak_system


def converse(session: Session, llm: LLMClient, a: Clone, b: Clone, tick: int, location: str) -> str:
    """安排 a 与 b 在 location 进行一轮双人对话，双方各记一条对话记忆。"""
    line_a = llm.complete(
        speak_system(f"你是{a.name}，正在与{b.name}偶遇闲聊。依据你的性格说话，只说一句。"),
        f"TASK:social_turn\nNAME:{a.name}\nPARTNER:{b.name}\nLOCATION:{location}",
    ).strip() or f"{a.name}：「嘿，{b.name}。」"
    line_b = llm.complete(
        speak_system(f"你是{b.name}，回应{a.name}刚才的话。依据你的性格说话，只说一句。"),
        f"TASK:social_turn\nNAME:{b.name}\nPARTNER:{a.name}\nLOCATION:{location}",
    ).strip() or f"{b.name}：「哟，{a.name}，好久不见。」"

    memory_mod.add_memory(
        session, llm, a.id,
        content=f"在{location}遇到{b.name}，我说：{line_a}；对方回应：{line_b}",
        kind="conversation",
    )
    memory_mod.add_memory(
        session, llm, b.id,
        content=f"在{location}遇到{a.name}，{a.name}说：{line_a}；我回应：{line_b}",
        kind="conversation",
    )
    a.since_reflect += 1
    b.since_reflect += 1
    return f"【{location}】{a.name} 与 {b.name} 聊了天。\n{line_a}\n{line_b}"
