"""演进时间线：汇总一个复制人的 profile 版本、重要记忆与模拟事件。

供「无限迭代」视图展示：克隆从哪里来（interview/chat_session/upload/quick），
又如何经由聊天、上传、模拟社会持续演进（reflection patch，版本无封顶）。
"""

from __future__ import annotations

import json

from sqlmodel import Session, select

from .db import Clone, Memory, SimEvent
from .persona import profile as profile_mod

# 进入时间线的记忆门槛：反思记忆全部收录，其余只收录高重要度
TIMELINE_MEMORY_IMPORTANCE = 7


def build_timeline(session: Session, clone_id: int) -> list[dict]:
    clone = session.get(Clone, clone_id)
    if clone is None:
        raise KeyError(f"复制人 {clone_id} 不存在")

    items: list[dict] = []

    for v in profile_mod.history(session, clone_id):
        items.append(
            {
                "ts": v.created_at,
                "type": "profile_version",
                "source": v.source,
                "title": f"人格档案 v{v.version}",
                "detail": v.diff_reason or "",
                "traits": json.loads(v.traits_json),
                "values": json.loads(v.values_json),
            }
        )

    rows = session.exec(select(Memory).where(Memory.clone_id == clone_id).order_by(Memory.id)).all()
    for m in rows:
        if m.kind == "reflection" or m.importance >= TIMELINE_MEMORY_IMPORTANCE:
            items.append(
                {
                    "ts": m.created_at,
                    "type": "memory",
                    "source": m.kind,
                    "title": f"记忆（{m.kind}，重要度 {m.importance}）",
                    "detail": m.content,
                }
            )

    events = session.exec(select(SimEvent).order_by(SimEvent.tick, SimEvent.id)).all()
    for e in events:
        if clone_id in (json.loads(e.actors_json) or []):
            items.append(
                {
                    "ts": e.created_at,
                    "type": "sim_event",
                    "source": "simulation",
                    "title": f"模拟世界 tick {e.tick} · {e.kind}",
                    "detail": e.description,
                }
            )

    items.sort(key=lambda x: x["ts"])
    return items
