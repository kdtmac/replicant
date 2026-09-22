"""访谈状态机推进测试：全部走 MockLLM。"""

from __future__ import annotations

from sqlmodel import select

from replicant.db import Clone, Interview, PersonaProfile
from replicant.interview import engine, protocol


def _run_reply(session, llm, iv_id, text):
    return engine.handle_reply(session, llm, iv_id, text)


def test_protocol_convergence_rule():
    # min_rounds 未达 + 回答有效 → 不推进
    assert not protocol.should_advance("life_story", 1, "我在小城长大，后来去了北京。")
    # 达到 min_rounds + 回答有效 → 推进
    assert protocol.should_advance("life_story", 2, "我在小城长大，后来去了北京。")
    # 达到 min_rounds 但回答敷衍 → 不推进
    assert not protocol.should_advance("intro", 1, "嗯。")
    # 达到 max_rounds → 强制推进
    assert protocol.should_advance("intro", 2, "嗯。")


def test_stage_progression_and_clone_creation(session, llm):
    """3~5 轮走完访谈（走最短路径的 min_rounds），产出 clone 与 profile v1。"""
    started = engine.start_interview(session, llm, "张三")
    iv_id = started["interview_id"]
    assert started["stage"] == "intro"
    assert "自我介绍" in started["question"] or "叫什么名字" in started["question"]

    # intro：1 轮（min_rounds=1）
    r = _run_reply(session, llm, iv_id, "我叫张三，是个开朗乐观的程序员，喜欢交朋友。")
    assert r["stage"] == "life_story"

    # life_story：2 轮
    r = _run_reply(session, llm, iv_id, "我在南方小城长大，大学去了北方，那是重要转折。")
    assert r["stage"] == "life_story"
    r = _run_reply(session, llm, iv_id, "影响我最大的是我的高中老师，他教会我认真。")
    assert r["stage"] == "values"

    # values：2 轮
    r = _run_reply(session, llm, iv_id, "我最看重家庭和自由，不喜欢为了金钱牺牲生活。")
    assert r["stage"] == "values"
    r = _run_reply(session, llm, iv_id, "我希望自己十年后还坚持诚实的原则。")
    assert r["stage"] == "habits"

    # habits：1 轮
    r = _run_reply(session, llm, iv_id, "我一般七点起床，空闲喜欢看书和跑步。")
    assert r["stage"] == "style_sampling"

    # style_sampling：2 轮
    r = _run_reply(session, llm, iv_id, "别慌，天塌不下来。")
    assert r["stage"] == "style_sampling"
    r = _run_reply(session, llm, iv_id, "这天气真是要命，出门就被蒸熟。")
    assert r["status"] == "done"
    clone_id = r["clone_id"]
    assert clone_id is not None

    # 落库校验：clone + profile v1 + 抽取出的结构化信息
    clone = session.get(Clone, clone_id)
    assert clone.name == "张三"
    profile = session.exec(select(PersonaProfile).where(PersonaProfile.clone_id == clone_id)).one()
    assert profile.version == 1
    assert "开朗" in profile.traits_json and "乐观" in profile.traits_json
    assert "家庭" in profile.values_json and "自由" in profile.values_json
    assert "天塌不下来" in profile.style_samples_json

    # done 后再 reply 幂等返回 done
    again = _run_reply(session, llm, iv_id, "还有问题吗？")
    assert again["status"] == "done" and again["clone_id"] == clone_id


def test_short_answer_stays_in_stage(session, llm):
    """敷衍回答不计入有效轮数，停留在当前阶段。"""
    started = engine.start_interview(session, llm, "李四")
    r = _run_reply(session, llm, started["interview_id"], "嗯。")
    assert r["stage"] == "intro"
    assert r["status"] == "active"
    iv = session.get(Interview, started["interview_id"])
    assert iv.stage == "intro" and iv.stage_round == 1
