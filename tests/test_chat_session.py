"""即时聊天会话全流程测试：开会话 → 自由聊天累积草稿 → finalize → 继续聊迭代。"""

from __future__ import annotations

import json

from sqlmodel import select

from replicant import chatsession
from replicant.db import ChatSession, Clone, Memory
from replicant.persona import profile as profile_mod


def test_chat_session_flow_and_finalize(session, llm):
    started = chatsession.start_session(session, llm, "王五")
    sid = started["session_id"]
    assert not started["ready"]

    # 前两轮未达到就绪阈值
    r = chatsession.send_message(session, llm, sid, "我叫王五，是个开朗的人，平时喜欢早起跑步。")
    assert r["status"] == "active" and not r["ready"]
    r = chatsession.send_message(session, llm, sid, "我最看重家庭和朋友，钱够用就行。")
    assert not r["ready"]

    # 第三轮达到轻量阈值，ready，但草稿仍在累积
    r = chatsession.send_message(session, llm, sid, "别慌，问题不大，慢慢来。")
    assert r["ready"] and r["draft_facts"] >= 3
    cs = session.get(ChatSession, sid)
    draft = json.loads(cs.extracted_json)
    assert "开朗" in draft["traits"]
    assert "家庭" in draft["values"]
    assert any("别慌，问题不大" in s for s in draft["style_samples"])

    # 手动 finalize → 克隆 + profile v1（来源 chat_session）
    fin = chatsession.finalize(session, llm, sid)
    clone_id = fin["clone_id"]
    assert fin["status"] == "finalized"
    clone = session.get(Clone, clone_id)
    assert clone.name == "王五"
    v1 = profile_mod.latest_profile(session, clone_id)
    assert v1.version == 1 and v1.source == "chat_session"

    # finalize 幂等
    again = chatsession.finalize(session, llm, sid)
    assert again["clone_id"] == clone_id

    # 定型后继续发消息 = 与克隆聊天迭代，记忆照常增长
    r = chatsession.send_message(session, llm, sid, "最近压力大怎么办？")
    assert r["status"] == "finalized" and r["reply"]
    mems = session.exec(select(Memory).where(Memory.clone_id == clone_id)).all()
    assert any(m.kind == "chat" for m in mems)


def test_chat_session_continue_chat_can_patch(session, llm):
    """定型后继续聊天达到反思阈值 → profile 继续出新版本（无封顶）。"""
    sid = chatsession.start_session(session, llm, "王五")["session_id"]
    for _ in range(3):
        chatsession.send_message(session, llm, sid, "我随便聊聊，讲讲我最近的事。")
    clone_id = chatsession.finalize(session, llm, sid)["clone_id"]
    assert profile_mod.latest_profile(session, clone_id).version == 1

    # 每条消息 +2 反思计数；连续 2 条（4 ≥ 3）触发一次反思 → v2
    chatsession.send_message(session, llm, sid, "再聊一句。")
    chatsession.send_message(session, llm, sid, "再聊一句。")
    assert profile_mod.latest_profile(session, clone_id).version == 2
    # 继续聊 → v3，证明无封顶
    chatsession.send_message(session, llm, sid, "再聊一句。")
    chatsession.send_message(session, llm, sid, "再聊一句。")
    assert profile_mod.latest_profile(session, clone_id).version == 3


def test_auto_finalize_threshold(session, llm, monkeypatch):
    """配置自动定型阈值后，消息数到点自动产出克隆。"""
    monkeypatch.setenv("REPLICANT_AUTO_FINALIZE_MSGS", "2")
    sid = chatsession.start_session(session, llm, "自动用户")["session_id"]
    chatsession.send_message(session, llm, sid, "第一句话。")
    r = chatsession.send_message(session, llm, sid, "第二句话，自动定型。")
    assert r["status"] == "finalized" and r["clone_id"] is not None


def test_session_name_fallback_chain(session, llm):
    """名字兜底链：创建时传入的名字 > 聊天中抽取的自称 > 匿名。"""
    # 1) 传了名字：即使聊天里自称别的，也用传入的名字
    sid = chatsession.start_session(session, llm, "调试用户")["session_id"]
    chatsession.send_message(session, llm, sid, "我叫王五，是个开朗的人。")
    clone_id = chatsession.finalize(session, llm, sid)["clone_id"]
    clone = session.get(Clone, clone_id)
    assert clone.name == "调试用户"
    assert profile_mod.latest_profile(session, clone_id).name == "调试用户"

    # 2) 没传名字：回落到聊天中抽取的自称
    sid2 = chatsession.start_session(session, llm, "匿名")["session_id"]
    chatsession.send_message(session, llm, sid2, "我叫王五，是个开朗的人。")
    clone_id2 = chatsession.finalize(session, llm, sid2)["clone_id"]
    assert session.get(Clone, clone_id2).name == "王五"

    # 3) 既没传名字也没自称：最终兜底为匿名
    sid3 = chatsession.start_session(session, llm, "匿名")["session_id"]
    chatsession.send_message(session, llm, sid3, "今天天气真不错。")
    clone_id3 = chatsession.finalize(session, llm, sid3)["clone_id"]
    assert session.get(Clone, clone_id3).name == "匿名"
