"""即时聊天会话相关 REST API（复制人创建方式之二）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, desc, select

from .. import chatsession
from ..db import ChatMessage, ChatSession, get_llm, get_session
from ..llm import LLMClient

router = APIRouter()


class StartIn(SQLModel):
    # 两种字段名都接受：name 优先，owner_name 兼容旧调用
    name: str | None = None
    owner_name: str | None = None


class MsgIn(SQLModel):
    text: str


@router.post("/chat-sessions")
def start(payload: StartIn, session: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    """开始即时聊天会话：无进度条，后台持续抽取事实累积草稿 profile。

    创建时传入的名字会作为种子写入草稿，finalize 时落到克隆与 profile 的 name 上。
    """
    owner_name = (payload.name or payload.owner_name or "").strip() or "匿名"
    return chatsession.start_session(session, llm, owner_name)


@router.post("/chat-sessions/{session_id}/msg")
def msg(
    session_id: int,
    payload: MsgIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    """发一句：未定型时累积草稿并闲聊回应；已定型时等同与克隆继续聊天迭代。"""
    try:
        return chatsession.send_message(session, llm, session_id, payload.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/chat-sessions/{session_id}/msg/stream")
def msg_stream(
    session_id: int,
    payload: MsgIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    """流式发消息（SSE）：status → reasoning* → delta* → done（与同步返回相同）。"""
    from .sse import sse

    return sse(chatsession.send_message_stream(session, llm, session_id, payload.text))


@router.post("/chat-sessions/{session_id}/finalize")
def finalize(
    session_id: int,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    """随时定型：用累积草稿产出 Clone + PersonaProfile v1（幂等）。"""
    try:
        return chatsession.finalize(session, llm, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/chat-sessions")
def list_sessions(session: Session = Depends(get_session)):
    """列出即时聊天会话：active 排前，供「继续聊」入口恢复上下文。"""
    rows = session.exec(select(ChatSession).order_by(ChatSession.id)).all()
    result = []
    for cs in rows:
        latest = session.exec(
            select(ChatMessage)
            .where(ChatMessage.thread_type == "chat_session", ChatMessage.thread_id == cs.id)
            .order_by(desc(ChatMessage.id))
        ).first()
        result.append({
            "id": cs.id,
            "owner_name": cs.owner_name,
            "status": cs.status,
            "msg_count": cs.msg_count,
            "clone_id": cs.clone_id,
            "last_message_preview": (latest.text[:40] if latest else None),
            "updated_at": latest.created_at if latest else cs.created_at,
        })
    # active 优先，其次按更新时间倒序
    result.sort(key=lambda s: (s["status"] != "active", -s["updated_at"]))
    return result


@router.get("/chat-sessions/{session_id}/messages")
def session_messages(session_id: int, session: Session = Depends(get_session)):
    """会话完整原始消息 + 草稿状态：供刷新后恢复历史、接着聊。"""
    cs = session.get(ChatSession, session_id)
    if cs is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.thread_type == "chat_session", ChatMessage.thread_id == session_id)
        .order_by(ChatMessage.id)
    ).all()
    return {
        "session_id": cs.id,
        "owner_name": cs.owner_name,
        "status": cs.status,
        "clone_id": cs.clone_id,
        "msg_count": cs.msg_count,
        "ready": cs.msg_count >= chatsession.READY_MIN_MSGS,
        "messages": [{"role": m.role, "text": m.text, "created_at": m.created_at} for m in rows],
    }
