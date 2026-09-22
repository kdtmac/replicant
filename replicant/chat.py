"""与复制人对话：profile + top-K 记忆 → prompt 组装 → LLM 回答。

关键约束：聊天内容只抽成记忆写入记忆流，绝不静默修改人格 profile；
profile 的演进只能经由 reflection 产生的显式版本更新。

流式变体 chat_with_clone_stream 与同步版副作用一致，
只是通过生成器把 status / reasoning / delta / done 事件实时推给 SSE 层。
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session

from .db import Clone
from .llm import LLMClient
from .persona import memory as memory_mod
from .persona import profile as profile_mod
from .style import speak_system

TOP_K = 5


def build_chat_prompt(profile: dict, memories: list, message: str) -> tuple[str, str]:
    """组装 (system, user) 两段 prompt。返回元组便于测试检查内容。"""
    system = speak_system(
        f"你是 {profile['name']} 的复制人。请严格依据人格档案与相关记忆，以第一人称、用档案语言风格回答。"
    )
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
    reply = llm.complete(system, user).strip() or "……（我一时没接上话，你再说一遍？）"

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


def chat_with_clone_stream(
    session: Session, llm: LLMClient, clone_id: int, message: str
) -> Iterator[tuple[str, object]]:
    """流式对话：检索记忆与生成逐字推进；副作用与同步版完全一致。

    事件序列：status → status → reasoning*/delta* → done（载荷与同步返回相同）。
    """
    clone = session.get(Clone, clone_id)
    if clone is None:
        yield ("error", f"复制人 {clone_id} 不存在")
        return
    profile_row = profile_mod.latest_profile(session, clone_id)
    if profile_row is None:
        yield ("error", f"复制人 {clone_id} 没有人格档案")
        return
    profile = profile_mod.to_dict(profile_row)

    yield ("status", "正在回忆你之前说过的事…")
    memories = memory_mod.retrieve(session, clone_id, query=message, k=TOP_K)
    if memories:
        yield ("status", f"想起了 {len(memories)} 件你之前说过的事，正在琢磨…")
    else:
        yield ("status", "正在想怎么跟你说…")

    system, user = build_chat_prompt(profile, memories, message)
    chunks: list[str] = []
    for kind, payload in llm.chat_stream([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]):
        if kind == "content":
            chunks.append(payload)
        yield (kind, payload)
    reply = "".join(chunks).strip() or "……（我一时没接上话，你再说一遍？）"
    if not chunks:
        yield ("content", reply)  # 模型完全无输出时也要给前端一个定稿气泡

    memory_mod.add_memory(session, llm, clone_id, content=f"用户对我说：{message}", kind="chat")
    memory_mod.add_memory(session, llm, clone_id, content=f"我回答用户：{reply}", kind="chat")
    clone.since_reflect += 2
    reflection = memory_mod.maybe_reflect(session, llm, clone_id)
    session.commit()

    yield ("done", {
        "clone_id": clone_id,
        "reply": reply,
        "profile_version": profile_row.version,
        "used_memory_ids": [m.id for m in memories],
        "reflected": reflection is not None,
    })
