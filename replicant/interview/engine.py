"""访谈引擎：状态由表持久化，引擎函数无状态，可多请求推进。

每轮流程：
1. 记录用户回答；
2. 调用 LLM 从回答抽取结构化信息（facts/traits/values/name/style_sample）；
3. 状态机判据决定是否进入下一阶段；
4. 未收敛 → LLM 生成下一问题；收敛 → 产出 PersonaProfile v1 + Clone。
"""

from __future__ import annotations

import json

from sqlmodel import Session

from ..db import Clone, Interview, InterviewTurn, SimState
from ..llm import LLMClient, parse_json_loose
from ..persona.memory import add_memory
from ..persona.profile import create_initial_profile
from . import protocol


def _extracted(interview: Interview) -> dict:
    try:
        data = json.loads(interview.extracted_json)
    except json.JSONDecodeError:
        data = {}
    return {
        "name": data.get("name"),
        "facts": list(data.get("facts", [])),
        "traits": list(data.get("traits", [])),
        "values": list(data.get("values", [])),
        "style_samples": list(data.get("style_samples", [])),
    }


def _merge(extracted: dict, new: dict | None) -> dict:
    if not new:
        return extracted
    if new.get("name"):
        extracted["name"] = new["name"]
    for key_in, key_out in (("facts", "facts"), ("traits", "traits"), ("values", "values")):
        for item in new.get(key_in) or []:
            if item not in extracted[key_out]:
                extracted[key_out].append(item)
    if new.get("style_sample"):
        extracted["style_samples"].append(new["style_sample"])
    return extracted


def _ask_question(session: Session, llm: LLMClient, interview: Interview) -> str:
    system = "你是一个温和的人格访谈员，根据指定访谈阶段生成下一个问题，只输出问题本身。"
    user = f"TASK:interview_question\nSTAGE:{interview.stage}\nROUND:{interview.stage_round}"
    question = llm.complete(system, user).strip()
    session.add(InterviewTurn(interview_id=interview.id, role="agent", text=question, stage=interview.stage))
    return question


def start_interview(session: Session, llm: LLMClient, owner_name: str) -> dict:
    interview = Interview(owner_name=owner_name)
    session.add(interview)
    session.flush()
    question = _ask_question(session, llm, interview)
    session.commit()
    return {"interview_id": interview.id, "question": question, "stage": interview.stage, "status": interview.status}


def handle_reply(session: Session, llm: LLMClient, interview_id: int, text: str) -> dict:
    interview = session.get(Interview, interview_id)
    if interview is None:
        raise KeyError(f"访谈 {interview_id} 不存在")
    if interview.status == "done":
        return {"status": "done", "clone_id": interview.clone_id, "question": None, "stage": None}

    session.add(InterviewTurn(interview_id=interview.id, role="user", text=text, stage=interview.stage))

    # LLM 抽取结构化信息（只负责填空，不做决策）
    extract_prompt = (
        f"TASK:extract\nSTAGE:{interview.stage}\n"
        f"从用户回答中抽取结构化信息，输出 JSON：\n用户回答：{text}"
    )
    new_info = parse_json_loose(llm.complete("你是信息抽取器，只输出 JSON。", extract_prompt))
    extracted = _merge(_extracted(interview), new_info)
    interview.extracted_json = json.dumps(extracted, ensure_ascii=False)

    interview.stage_round += 1
    if protocol.should_advance(interview.stage, interview.stage_round, text):
        nxt = protocol.next_stage(interview.stage)
        if nxt is None:
            return _finish(session, llm, interview, extracted)
        interview.stage = nxt
        interview.stage_round = 0

    question = _ask_question(session, llm, interview)
    session.commit()
    return {"status": "active", "stage": interview.stage, "question": question, "clone_id": None}


def _finish(session: Session, llm: LLMClient, interview: Interview, extracted: dict) -> dict:
    """访谈收敛：落库 Clone + PersonaProfile v1。"""
    clone = Clone(name=extracted["name"] or interview.owner_name)
    session.add(clone)
    session.flush()
    create_initial_profile(
        session,
        clone_id=clone.id,
        name=clone.name,
        traits=extracted["traits"],
        values=extracted["values"],
        facts=extracted["facts"],
        style_samples=extracted["style_samples"],
        diff_reason="访谈收敛，建立初始人格档案 v1",
    )
    interview.status = "done"
    interview.clone_id = clone.id
    _ensure_sim_state(session)
    session.commit()
    # 访谈本身作为初始记忆写入记忆流
    add_memory(
        session,
        llm,
        clone_id=clone.id,
        content=f"我完成了一次人格访谈，建立了我的复制人档案（v1）。",
        kind="interview",
    )
    session.commit()
    return {"status": "done", "clone_id": clone.id, "question": None, "stage": None}


def _ensure_sim_state(session: Session) -> None:
    if session.get(SimState, 1) is None:
        session.add(SimState(id=1, tick=0))
