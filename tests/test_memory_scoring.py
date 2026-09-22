"""记忆流三因子打分测试：score = α·recency + β·importance + γ·relevance。"""

from __future__ import annotations

import re

from replicant.llm import MockLLM
from replicant.persona import memory as memory_mod


def test_scoring_formula_and_order(session, llm):
    clone_id = 1
    # 依次写入三条记忆：旧且重要，中等平庸，新且与查询相关
    old_important = memory_mod.add_memory(session, llm, clone_id, "我经历了一次重大转折", importance=9)
    mid = memory_mod.add_memory(session, llm, clone_id, "今天天气不错", importance=5)
    new_relevant = memory_mod.add_memory(session, llm, clone_id, "我喜欢猫，猫很可爱", importance=3)
    session.commit()

    query = "猫"
    latest_id = new_relevant.id
    expected = {}
    for m, q_rel in (
        (old_important, memory_mod.relevance(query, old_important.content)),
        (mid, memory_mod.relevance(query, mid.content)),
        (new_relevant, memory_mod.relevance(query, new_relevant.content)),
    ):
        expected[m.id] = (
            memory_mod.WEIGHT_RECENCY * (memory_mod.RECENCY_DECAY ** (latest_id - m.id))
            + memory_mod.WEIGHT_IMPORTANCE * (m.importance / 10)
            + memory_mod.WEIGHT_RELEVANCE * q_rel
        )

    top = memory_mod.retrieve(session, clone_id, query=query, k=1)[0]
    # 与查询最相关的新记忆应排第一
    assert top.id == new_relevant.id
    assert expected[new_relevant.id] > expected[mid.id]
    assert expected[old_important.id] > 0


def test_recency_decays_with_age(session, llm):
    old = memory_mod.add_memory(session, llm, 1, "很久以前的小事", importance=5)
    for i in range(3):
        memory_mod.add_memory(session, llm, 1, f"最近的小事 {i}", importance=5)
    session.commit()
    results = memory_mod.retrieve(session, 1, query="小事", k=10)
    ids = [m.id for m in results]
    assert old.id == ids[-1]  # 同 importance 同 relevance 时，最旧的排最后


def test_importance_by_llm_is_clamped(session):
    llm = MockLLM()
    low = memory_mod.add_memory(session, llm, 1, "吃了一碗面")
    high = memory_mod.add_memory(session, llm, 1, "这是一次重要的人生转折点")
    assert 1 <= low.importance <= 10
    assert high.importance == 9  # 命中重大/转折关键词
    # Mock 分数字符串可被正则解析
    # Mock 的打分响应可被解析为 1-10 的整数
    resp = llm.complete("", "TASK:importance\n内容：这是一次重要的人生转折点")
    assert re.search(r"\d+", resp) and int(re.search(r"\d+", resp).group()) == 9


def test_relevance_token_overlap():
    assert memory_mod.relevance("猫", "我喜欢猫") == 1.0
    assert memory_mod.relevance("猫", "我喜欢狗") == 0.0
    assert 0 < memory_mod.relevance("我喜欢猫", "我喜欢狗") < 1.0


def test_reflection_produces_insight_and_patch(session, llm):
    clone_id = 1
    from replicant.db import Clone
    from replicant.persona import profile as profile_mod

    session.add(Clone(id=clone_id, name="测试人"))
    profile_mod.create_initial_profile(session, clone_id, name="测试人", traits=["开朗"])
    # 积累到反思阈值
    for i in range(3):
        memory_mod.add_memory(session, llm, clone_id, f"社交经历 {i}", kind="conversation")
        session.get(Clone, clone_id).since_reflect += 1
    session.commit()

    result = memory_mod.maybe_reflect(session, llm, clone_id, allow_patch=True)
    assert result is not None and result["patched"] is True
    # 反思记忆写入 + 人格档案出现 v2
    memories = memory_mod.retrieve(session, clone_id, query="反思", k=10)
    assert any(m.kind == "reflection" for m in memories)
    latest = profile_mod.latest_profile(session, clone_id)
    assert latest.version == 2
    assert "善于从社会交往中反思" in latest.traits_json
    assert latest.diff_reason
    # 重复补丁去重后不产生空版本
    assert profile_mod.apply_patch(session, clone_id, add_trait="善于从社会交往中反思", diff_reason="重复") is None
    assert profile_mod.latest_profile(session, clone_id).version == 2
