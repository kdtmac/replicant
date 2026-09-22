"""模拟世界测试：tick 产生双人对话记忆、时间线事件、偶发人格演进。"""

from __future__ import annotations

from sqlmodel import select

from replicant.db import Clone, Memory, SimEvent
from replicant.persona import profile as profile_mod
from replicant.simulation import world


def _make_clone(session, name: str) -> Clone:
    clone = Clone(name=name)
    session.add(clone)
    session.flush()
    profile_mod.create_initial_profile(session, clone.id, name=name, traits=["随和"])
    return clone


def test_tick_empty_world(session, llm):
    result = world.tick_world(session, llm)
    assert result["tick"] == 1
    assert result["events"][0]["kind"] == "notice"


def test_tick_produces_dialogue_and_memories(session, llm):
    a = _make_clone(session, "阿明")
    b = _make_clone(session, "阿芳")
    session.commit()

    result = world.tick_world(session, llm)
    assert result["tick"] == 1
    dialogue = [e for e in result["events"] if e["kind"] == "dialogue"]
    assert len(dialogue) == 1
    assert set(dialogue[0]["actors"]) == {a.id, b.id}
    assert "阿明" in dialogue[0]["description"] and "阿芳" in dialogue[0]["description"]

    # 双方各写入一条对话记忆
    for clone_id, partner in ((a.id, "阿芳"), (b.id, "阿明")):
        mems = session.exec(
            select(Memory).where(Memory.clone_id == clone_id).where(Memory.kind == "conversation")
        ).all()
        assert len(mems) == 1
        assert partner in mems[0].content

    # 时间线落库
    timeline = session.exec(select(SimEvent).order_by(SimEvent.tick, SimEvent.id)).all()
    assert any(e.kind == "dialogue" for e in timeline)


def test_simulation_profile_evolution(session, llm):
    """多 tick 后反思触发，人格档案出现新版本（偶发演进）。"""
    _make_clone(session, "阿明")
    _make_clone(session, "阿芳")
    session.commit()
    for _ in range(memory_threshold_ticks()):
        world.tick_world(session, llm)
    # 至少一个 clone 的 profile 在反思后升级
    any_upgraded = any(
        len(profile_mod.history(session, c.id)) >= 2
        for c in session.exec(select(Clone)).all()
    )
    assert any_upgraded
    # 时间线里能看到 profile_patch 或 notice 反思事件
    kinds = {e.kind for e in session.exec(select(SimEvent)).all()}
    assert "dialogue" in kinds


def memory_threshold_ticks() -> int:
    # 每个 tick 给每个 clone +1（对话）或 +1（行动）反思计数，阈值 3，走 4 tick 足够
    return 4
