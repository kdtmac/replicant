"""复制人相关 REST API。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from ..chat import chat_with_clone, chat_with_clone_stream
from ..chatlog_parser import NoOwnerMessageError
from ..db import ChatMessage, Clone, Memory, get_llm, get_session
from ..llm import LLMClient
from ..persona import profile as profile_mod
from ..timeline import build_timeline
from ..upload import create_clone_from_upload
from .sse import sse

router = APIRouter()


class ChatIn(SQLModel):
    message: str


class QuickCloneIn(SQLModel):
    name: str
    traits: list[str] = []
    values: list[str] = []
    facts: list[str] = []
    style_samples: list[str] = []


class UploadIn(SQLModel):
    text: str
    alias: str  # 聊天记录中“本人”的昵称
    owner_name: str | None = None  # 克隆显示名，缺省用 alias


@router.get("/clones")
def list_clones(session: Session = Depends(get_session)):
    clones = session.exec(select(Clone).order_by(Clone.id)).all()
    result = []
    for c in clones:
        profile = profile_mod.latest_profile(session, c.id)
        result.append({
            "id": c.id,
            "name": c.name,
            "profile_version": profile.version if profile else None,
            "traits": json.loads(profile.traits_json)[:4] if profile else [],
        })
    return result


@router.post("/clones/quick")
def quick_clone(payload: QuickCloneIn, session: Session = Depends(get_session)):
    """调试入口：越过访谈直接创建人格档案 v1（常规路径仍是访谈）。"""
    clone = Clone(name=payload.name)
    session.add(clone)
    session.flush()
    profile = profile_mod.create_initial_profile(
        session,
        clone_id=clone.id,
        name=payload.name,
        traits=payload.traits,
        values=payload.values,
        facts=payload.facts,
        style_samples=payload.style_samples,
        diff_reason="调试入口直接建档 v1",
        source="quick",
    )
    session.commit()
    return {"clone_id": clone.id, "profile_version": profile.version}


@router.post("/clones/upload")
def upload(
    payload: UploadIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    """上传聊天记录快速生成（创建方式之三）：
    解析文本 → 只取本人消息 → 批量抽取 → 立即产出 profile v1 和克隆（无需多轮）。"""
    try:
        return create_clone_from_upload(session, llm, payload.text, alias=payload.alias, owner_name=payload.owner_name)
    except NoOwnerMessageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/clones/{clone_id}")
def get_clone(clone_id: int, session: Session = Depends(get_session)):
    clone = session.get(Clone, clone_id)
    if clone is None:
        raise HTTPException(status_code=404, detail=f"复制人 {clone_id} 不存在")
    profile = profile_mod.latest_profile(session, clone_id)
    return {"id": clone.id, "name": clone.name, "profile": profile_mod.to_dict(profile) if profile else None}


@router.post("/clones/{clone_id}/chat")
def chat(
    clone_id: int,
    payload: ChatIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    """与复制人对话：profile + top-K 记忆组装 prompt；聊天只写记忆，不改 profile。"""
    try:
        return chat_with_clone(session, llm, clone_id, payload.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/clones/{clone_id}/chat/stream")
def chat_stream(
    clone_id: int,
    payload: ChatIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    """流式聊天（SSE）：status（检索记忆/思考）→ reasoning* → delta* → done（与同步返回相同）。"""
    return sse(chat_with_clone_stream(session, llm, clone_id, payload.message))


@router.get("/clones/{clone_id}/profile-history")
def profile_history(clone_id: int, session: Session = Depends(get_session)):
    """人格演进版本史：每个版本附来源与 diff 原因。"""
    versions = profile_mod.history(session, clone_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"复制人 {clone_id} 没有人格档案")
    return [profile_mod.to_dict(v) for v in versions]


@router.get("/clones/{clone_id}/timeline")
def timeline(clone_id: int, session: Session = Depends(get_session)):
    """演进时间线：profile 版本 + 重要记忆 + 模拟事件汇成一条流（无限迭代视图）。"""
    try:
        return build_timeline(session, clone_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/clones/{clone_id}/memories")
def memories(clone_id: int, session: Session = Depends(get_session)):
    """查看记忆流（调试用）。"""
    rows = session.exec(select(Memory).where(Memory.clone_id == clone_id).order_by(Memory.id)).all()
    return [
        {"id": m.id, "content": m.content, "kind": m.kind, "importance": m.importance, "created_at": m.created_at}
        for m in rows
    ]


@router.get("/clones/{clone_id}/messages")
def clone_messages(clone_id: int, session: Session = Depends(get_session)):
    """克隆聊天的原始历史（clone_chat 线程）：供聊天页刷新后恢复。"""
    clone = session.get(Clone, clone_id)
    if clone is None:
        raise HTTPException(status_code=404, detail=f"复制人 {clone_id} 不存在")
    rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.thread_type == "clone_chat", ChatMessage.thread_id == clone_id)
        .order_by(ChatMessage.id)
    ).all()
    return {
        "clone_id": clone_id,
        "name": clone.name,
        "messages": [{"role": m.role, "text": m.text, "created_at": m.created_at} for m in rows],
    }
