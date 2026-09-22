"""模拟世界：tick 世界循环。

每次 tick：复制人两两相遇（偶数对按 id 排序配对，保证测试确定性）→ 双人对话
→ 记忆回写 → 落单者独立行动规划 → 达到阈值的复制人触发反思（偶发 profile patch）。
全部事件写入时间线。
"""

from __future__ import annotations

import json

from sqlmodel import Session, select

from ..db import Clone, SimEvent, SimState
from ..llm import LLMClient, LOCATIONS
from ..persona import memory as memory_mod
from ..persona import profile as profile_mod
from . import planner, social


def current_tick(session: Session) -> int:
    state = session.get(SimState, 1)
    return state.tick if state else 0


def _add_event(session: Session, tick: int, kind: str, description: str, actors: list[int] | None = None) -> SimEvent:
    event = SimEvent(tick=tick, kind=kind, description=description, actors_json=json.dumps(actors or []))
    session.add(event)
    session.flush()
    return event


def tick_world(session: Session, llm: LLMClient) -> dict:
    state = session.get(SimState, 1)
    if state is None:
        state = SimState(id=1, tick=0)
        session.add(state)
        session.flush()
    state.tick += 1
    tick = state.tick
    location = LOCATIONS[tick % len(LOCATIONS)]
    events: list[dict] = []

    clones = list(session.exec(select(Clone).order_by(Clone.id)))
    if not clones:
        _add_event(session, tick, "notice", "世界里还没有复制人，一片寂静。")
    elif len(clones) == 1:
        action = planner.plan_action(session, llm, clones[0], tick)
        _add_event(session, tick, "action", action, [clones[0].id])
    else:
        # 两两配对；落单的独立行动
        handled: list[int] = []
        for i in range(0, len(clones) - 1, 2):
            a, b = clones[i], clones[i + 1]
            desc = social.converse(session, llm, a, b, tick, location)
            _add_event(session, tick, "dialogue", desc, [a.id, b.id])
            handled += [a.id, b.id]
        for clone in clones:
            if clone.id not in handled:
                action = planner.plan_action(session, llm, clone, tick)
                _add_event(session, tick, "action", action, [clone.id])

    # 记忆积累达标的复制人偶发触发反思与 profile patch
    for clone in list(session.exec(select(Clone).order_by(Clone.id))):
        result = memory_mod.maybe_reflect(session, llm, clone.id, allow_patch=True)
        if result is None:
            continue
        desc = f"{clone.name} 完成了一次反思：{'；'.join(result['insights'])}"
        if result["patched"]:
            ver = profile_mod.latest_profile(session, clone.id).version
            desc += f"（人格档案已更新至 v{ver}）"
        _add_event(session, tick, "profile_patch" if result["patched"] else "notice", desc, [clone.id])

    session.commit()
    for event in session.exec(select(SimEvent).where(SimEvent.tick == tick).order_by(SimEvent.id)):
        events.append(
            {"id": event.id, "tick": event.tick, "kind": event.kind,
             "actors": json.loads(event.actors_json), "description": event.description}
        )
    return {"tick": tick, "events": events}
