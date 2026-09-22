"""与复制人对话：profile + top-K 记忆 → prompt 组装 → LLM 回答。

关键约束：聊天内容只抽成记忆写入记忆流，绝不静默修改人格 profile；
profile 的演进只能经由 reflection 产生的显式版本更新。
"""

from __future__ import annotations

from sqlmodel import Session

from .db import Clone
from .llm import LLMClient
from .persona import memory as memory_mod
from .persona import profile as profile_mod

TOP_K = 5


def build_chat_prompt(profile: dict, memories: list, message: str) -> tuple[str, str]:
    """组装 (system, user) 两段 prompt。返回元组便于测试检查内容。"""
    system = f"你是 {profile['name']} 的复制人。请严格依据人格档案与相关记忆，以第一人称、用档案语言风格回答。"
    mem_lines = "\n".join(f"- {m.content}" for m in memories) or "- （暂无相关记忆）"
    user = (
        "TASK:chat\n"
        f"NAME:{profile['name']}\n"
        f"TRAITS:{', '.join(profile['traits'])}\n"
        f"VALUES:{', '.join(profile['values'])}\n"
        f"FACTS:{'; '.join(profile['facts'])}\n"
        f"STYLE:{'; '.join(profile['style_samples'])}\n"
        f"最相关的记忆：\n{mem_lines}\n"
        f"用户：{message}"
    )
    return system, user


def chat_with_clone(session: Session, llm: LLMClient, clone_id: int, message: str) -> dict:
    clone = session.get(Clone, clone_id)
    if clone is None:
        raise KeyError(f"复制人 {clone_id} 不存在")
    profile_row = profile_mod.latest_profile(session, clone_id)
    if profile_row is None:
        raise KeyError(f"复制人 {clone_id} 没有人格档案")
    profile = profile_mod.to_dict(profile_row)

    memories = memory_mod.retrieve(session, clone_id, query=message, k=TOP_K)
    system, user = build_chat_prompt(profile, memories, message)
    reply = llm.complete(system, user).strip()

    # 只写记忆，不动 profile
    memory_mod.add_memory(session, llm, clone_id, content=f"用户对我说：{message}", kind="chat")
    memory_mod.add_memory(session, llm, clone_id, content=f"我回答用户：{reply}", kind="chat")
    clone.since_reflect += 2
    reflection = memory_mod.maybe_reflect(session, llm, clone_id)
    session.commit()

    return {
        "clone_id": clone_id,
        "reply": reply,
        "profile_version": profile_row.version,
        "used_memory_ids": [m.id for m in memories],
        "reflected": reflection is not None,
    }
