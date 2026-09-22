"""即时聊天模式：不做进度条式访谈，用户自由聊天，后台持续抽取事实累积草稿 profile。

- 每轮 /msg：后台抽取 facts/traits/values/style_sample 累积进会话草稿（JSON）；
- 消息数达到轻量阈值（READY_MIN_MSGS）后 ready=True，可随时 /finalize 定型产出克隆；
- 可通过配置自动定型阈值（REPLICANT_AUTO_FINALIZE_MSGS > 0 时到点自动 finalize）；
- 定型后继续发消息 = 与克隆自由聊天（走 chat_with_clone，记忆继续长、reflection 继续 patch）。
"""

from __future__ import annotations

import json
import os

from sqlmodel import Session

from .chat import chat_with_clone
from .db import ChatSession, Clone
from .interview.engine import EXTRACT_CONTRACT, empty_extracted, merge_extracted
from .llm import LLMClient, parse_json_loose
from .persona import memory as memory_mod, profile as profile_mod
from .style import speak_system

# 轻量阈值：消息数达到即可随时定型
READY_MIN_MSGS = 3


def _auto_finalize_msgs() -> int:
    try:
        return int(os.getenv("REPLICANT_AUTO_FINALIZE_MSGS", "0"))
    except ValueError:
        return 0


def _draft(cs: ChatSession) -> dict:
    try:
        data = json.loads(cs.extracted_json)
    except json.JSONDecodeError:
        return empty_extracted()
    return {
        "name": data.get("name"),
        "facts": list(data.get("facts", [])),
        "traits": list(data.get("traits", [])),
        "values": list(data.get("values", [])),
        "style_samples": list(data.get("style_samples", [])),
    }


def start_session(session: Session, llm: LLMClient, owner_name: str) -> dict:
    cs = ChatSession(owner_name=owner_name)
    session.add(cs)
    session.commit()
    return {
        "session_id": cs.id,
        "greeting": "不用按流程回答，随便聊——聊你的一天、你的想法、你的口头禅都可以。聊到差不多我会提醒你。",
        "status": cs.status,
        "msg_count": 0,
        "ready": False,
    }


def send_message(session: Session, llm: LLMClient, session_id: int, text: str) -> dict:
    cs = session.get(ChatSession, session_id)
    if cs is None:
        raise KeyError(f"会话 {session_id} 不存在")
    cs.msg_count += 1

    if cs.status == "finalized" and cs.clone_id is not None:
        # 已定型：继续聊 = 与克隆对话迭代（记忆增长，reflection 照常产出新 profile 版本）
        result = chat_with_clone(session, llm, cs.clone_id, text)
        session.commit()
        return {
            "status": "finalized",
            "session_id": cs.id,
            "clone_id": cs.clone_id,
            "msg_count": cs.msg_count,
            "ready": True,
            "reply": result["reply"],
            "profile_version": result["profile_version"],
        }

    # 未定型：后台抽取（结构化 prompt 不带口语风格） + 闲聊式回应（带风格）
    draft = _draft(cs)
    draft = merge_extracted(
        draft,
        parse_json_loose(
            llm.complete(
                "你是信息抽取器，只输出 JSON。",
                f"TASK:extract\nSTAGE:free_chat\n{EXTRACT_CONTRACT.format(stage='自由聊天')}\n用户回答：{text}",
            )
        ),
    )
    cs.extracted_json = json.dumps(draft, ensure_ascii=False)
    reply = llm.complete(
        speak_system("你是正在了解对方的陪聊朋友。回应要顺着对方的话说，偶尔自然地深挖一点。"),
        f"TASK:session_reply\n用户：{text}",
    ).strip() or "嗯嗯，我在听——你接着说。"

    ready = cs.msg_count >= READY_MIN_MSGS
    auto = _auto_finalize_msgs()
    if auto > 0 and cs.msg_count >= auto:
        fin = finalize(session, llm, session_id)
        return {
            **fin,
            "status": "finalized",
            "session_id": cs.id,
            "msg_count": cs.msg_count,
            "ready": True,
            "reply": reply + "（消息量已达自动定型阈值，克隆已生成）",
        }

    session.commit()
    return {
        "status": "active",
        "session_id": cs.id,
        "clone_id": None,
        "msg_count": cs.msg_count,
        "ready": ready,
        "reply": reply,
        "draft_facts": len(draft["facts"]),
    }


def finalize(session: Session, llm: LLMClient, session_id: int) -> dict:
    """定型：用草稿产出 Clone + PersonaProfile v1（幂等，重复调用返回同一克隆）。"""
    cs = session.get(ChatSession, session_id)
    if cs is None:
        raise KeyError(f"会话 {session_id} 不存在")
    if cs.status == "finalized" and cs.clone_id is not None:
        return {"status": "finalized", "clone_id": cs.clone_id}

    draft = _draft(cs)
    clone = Clone(name=draft["name"] or cs.owner_name)
    session.add(clone)
    session.flush()
    profile_mod.create_initial_profile(
        session,
        clone_id=clone.id,
        name=clone.name,
        traits=draft["traits"][:10],
        values=draft["values"][:10],
        facts=draft["facts"][:30],
        style_samples=draft["style_samples"][:10],
        diff_reason=f"即时聊天会话定型，建立初始人格档案 v1（{cs.msg_count} 条消息）",
        source="chat_session",
    )
    cs.status = "finalized"
    cs.clone_id = clone.id
    session.commit()
    memory_mod.add_memory(
        session, llm, clone_id=clone.id,
        content=f"我通过自由聊天建立了复制人档案（v1），聊了 {cs.msg_count} 条消息。",
        kind="chat_session",
    )
    session.commit()
    return {"status": "finalized", "clone_id": clone.id, "profile_version": 1}
