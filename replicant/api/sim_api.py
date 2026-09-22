"""模拟世界相关 REST API。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db import SimEvent, get_llm, get_session
from ..llm import LLMClient
from ..simulation import world

router = APIRouter()


@router.post("/sim/tick")
def tick(session: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    """驱动一次世界循环：行动规划 → 相遇 → 双人对话 → 记忆回写 → 偶发 profile patch。"""
    return world.tick_world(session, llm)


@router.get("/sim/timeline")
def timeline(session: Session = Depends(get_session)):
    """世界事件流，按 tick 与时间顺序排列。"""
    events = session.exec(select(SimEvent).order_by(SimEvent.tick, SimEvent.id)).all()
    return [
        {"id": e.id, "tick": e.tick, "kind": e.kind, "actors": json.loads(e.actors_json), "description": e.description}
        for e in events
    ]


@router.get("/sim/state")
def state(session: Session = Depends(get_session)):
    return {"tick": world.current_tick(session)}
