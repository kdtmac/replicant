"""聊天 prompt 组装内容测试：profile + top-K 记忆必须出现在 prompt 中。"""

from __future__ import annotations

from sqlmodel import select

from replicant.chat import build_chat_prompt, chat_with_clone
from replicant.db import Clone, Memory, PersonaProfile
from replicant.persona import memory as memory_mod, profile as profile_mod


def _setup_clone(session) -> int:
    clone = Clone(name="张三")
    session.add(clone)
    session.flush()
    profile_mod.create_initial_profile(
        session,
        clone_id=clone.id,
        name="张三",
        traits=["开朗", "幽默"],
        values=["家庭"],
        facts=["在南方小城长大"],
        style_samples=["别慌，天塌不下来。"],
    )
    return clone.id


def test_build_chat_prompt_contains_profile_and_memory(session, llm):
    clone_id = _setup_clone(session)
    memory_mod.add_memory(session, llm, clone_id, "用户对我说：你周末去哪玩", kind="chat", importance=5)
    memory_mod.add_memory(session, llm, clone_id, "我回答用户：去爬山了", kind="chat", importance=4)
    session.commit()
    memories = memory_mod.retrieve(session, clone_id, query="周末去哪玩", k=5)

    system, user = build_chat_prompt(profile_mod.to_dict(profile_mod.latest_profile(session, clone_id)), memories, "周末去哪玩？")
    assert "TASK:chat" in user
    assert "NAME:张三" in user
    assert "开朗" in user and "家庭" in user
    assert "在南方小城长大" in user
    assert "别慌，天塌不下来。" in user
    assert "用户：周末去哪玩？" in user
    assert any(m.content in user for m in memories)
    assert "张三" in system


def test_chat_writes_memory_but_keeps_profile(session, llm):
    """聊天只抽成记忆，不静默改 profile。"""
    clone_id = _setup_clone(session)
    session.commit()
    before = profile_mod.latest_profile(session, clone_id).version

    result = chat_with_clone(session, llm, clone_id, "最近心情不太好怎么办？")
    assert result["reply"]
    assert result["profile_version"] == before

    memories = session.exec(select(Memory).where(Memory.clone_id == clone_id).where(Memory.kind == "chat")).all()
    assert len(memories) == 2  # 用户一句 + 复制人一句
    assert any("最近心情不太好" in m.content for m in memories)

    # 未达反思阈值时 profile 不变
    after = profile_mod.latest_profile(session, clone_id).version
    assert after == before

    # 再聊一次（累计 4 ≥ 阈值 3）触发反思，偶发 profile patch
    chat_with_clone(session, llm, clone_id, "再聊聊吧")
    if memory_mod.REFLECTION_THRESHOLD <= 4:
        after2 = profile_mod.latest_profile(session, clone_id).version
        assert after2 >= before  # 若触发反思则版本 +1


def test_chat_prompt_recorded_by_mock(session, llm):
    clone_id = _setup_clone(session)
    session.commit()
    chat_with_clone(session, llm, clone_id, "你好")
    chat_calls = [c for c in llm.calls if c[1].startswith("TASK:chat")]
    assert len(chat_calls) == 1
    assert "用户：你好" in chat_calls[0][1]


def test_style_injected_into_speaking_prompts_only(session, llm):
    """开口说话的 system prompt 带口语风格；抽取/打分类 prompt 一律不带。"""
    from replicant.style import STYLE_GUIDE

    clone_id = _setup_clone(session)
    session.commit()
    chat_with_clone(session, llm, clone_id, "在吗")
    for system, user in llm.calls:
        if user.startswith("TASK:chat"):
            assert "单条消息很短" in system
        if user.startswith(("TASK:extract", "TASK:importance", "TASK:reflection")):
            assert STYLE_GUIDE not in system
    # 双克隆对话也注入风格
    from replicant.simulation.social import converse
    from replicant.db import Clone as _Clone

    a = session.get(_Clone, clone_id)
    other = _Clone(name="李四")
    session.add(other)
    session.flush()
    converse(session, llm, a, other, tick=1, location="公园")
    social_calls = [c for c in llm.calls if c[1].startswith("TASK:social_turn")]
    assert social_calls and all("先接住对方" in s for s, _ in social_calls)
