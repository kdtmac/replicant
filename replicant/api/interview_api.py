"""访谈相关 REST API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel

from ..db import get_llm, get_session
from ..interview import engine
from ..llm import LLMClient

router = APIRouter()


class StartIn(SQLModel):
    owner_name: str = "匿名"


class ReplyIn(SQLModel):
    text: str


@router.post("/interviews")
def start(payload: StartIn, session: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    """创建访谈：立刻返回第一轮提问。"""
    return engine.start_interview(session, llm, payload.owner_name)


@router.post("/interviews/{interview_id}/reply")
def reply(
    interview_id: int,
    payload: ReplyIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    """多轮推进：返回下一问题；访谈收敛时返回 status=done 与 clone_id。"""
    try:
        return engine.handle_reply(session, llm, interview_id, payload.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/interviews/{interview_id}/reply/stream")
def reply_stream(
    interview_id: int,
    payload: ReplyIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    """流式推进（SSE）：status（抽取/想问题）→ delta（问题逐字）→ done（与同步返回相同）。"""
    from .sse import sse

    return sse(engine.handle_reply_stream(session, llm, interview_id, payload.text))
