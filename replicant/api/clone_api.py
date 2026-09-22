"""复制人相关 REST API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from ..chat import chat_with_clone
from ..db import Clone, Memory, get_llm, get_session
from ..llm import LLMClient
from ..persona import profile as profile_mod

router = APIRouter()


class ChatIn(SQLModel):
    message: str


class QuickCloneIn(SQLModel):
    name: str
    traits: list[str] = []
    values: list[str] = []
    facts: list[str] = []
    style_samples: list[str] = []


@router.get("/clones")
def list_clones(session: Session = Depends(get_session)):
    clones = session.exec(select(Clone).order_by(Clone.id)).all()
    result = []
    for c in clones:
        profile = profile_mod.latest_profile(session, c.id)
        result.append({"id": c.id, "name": c.name, "profile_version": profile.version if profile else None})
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
    )
    session.commit()
    return {"clone_id": clone.id, "profile_version": profile.version}


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


@router.get("/clones/{clone_id}/profile-history")
def profile_history(clone_id: int, session: Session = Depends(get_session)):
    """人格演进版本史：每个版本附 diff 原因。"""
    versions = profile_mod.history(session, clone_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"复制人 {clone_id} 没有人格档案")
    return [profile_mod.to_dict(v) for v in versions]


@router.get("/clones/{clone_id}/memories")
def memories(clone_id: int, session: Session = Depends(get_session)):
    """查看记忆流（调试用）。"""
    rows = session.exec(select(Memory).where(Memory.clone_id == clone_id).order_by(Memory.id)).all()
    return [
        {"id": m.id, "content": m.content, "kind": m.kind, "importance": m.importance, "created_at": m.created_at}
        for m in rows
    ]
