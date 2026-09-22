"""即时聊天会话相关 REST API（复制人创建方式之二）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel

from .. import chatsession
from ..db import get_llm, get_session
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
