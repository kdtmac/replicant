"""访谈引擎：状态由表持久化，引擎函数无状态，可多请求推进。

每轮流程：
1. 记录用户回答；
2. 调用 LLM 从回答抽取结构化信息（facts/traits/values/name/style_sample）；
3. 状态机判据决定是否进入下一阶段；
4. 未收敛 → LLM 生成下一问题；收敛 → 产出 PersonaProfile v1 + Clone。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from sqlmodel import Session

from ..db import Clone, Interview, InterviewTurn, SimState, log_message
from ..llm import LLMClient, parse_json_loose
from ..persona import profile as profile_mod
from ..persona.memory import add_memory
from ..style import speak_system
from . import protocol


# 抽取 prompt 的输出契约（抽取类 prompt 不注入口语风格，保持 JSON 稳定）
EXTRACT_CONTRACT = (
    "从用户回答中抽取结构化信息，只输出 JSON，不要任何解释或 Markdown。字段："
    "facts（事实数组，每条以“（{stage}）”前缀转述）、"
    "traits（性格特质关键词数组）、values（价值观关键词数组）、"
    "name（用户自称的名字，未提及为 null）、style_sample（最有代表性的用户原句，可为 null）"
)


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


def empty_extracted() -> dict:
    return {"name": None, "facts": [], "traits": [], "values": [], "style_samples": []}


def merge_extracted(extracted: dict, new: dict | None) -> dict:
    """各轮抽取结果的累加合并（facts 精确去重追加，traits/values 归一化去重并集，name/style 覆盖追加）。

    访谈引擎与即时聊天会话共用此逻辑。traits/values 用归一化键比较，
    避免 "工作与生活平衡" / "工作生活平衡" 这类近义重复堆积。
    """
    if not new:
        return extracted
    if new.get("name"):
        extracted["name"] = new["name"]
    for item in new.get("facts") or []:
        if item not in extracted["facts"]:
            extracted["facts"].append(item)
    for key in ("traits", "values"):
        existing = {profile_mod.normalize_key(x) for x in extracted[key]}
        for item in new.get(key) or []:
            s = str(item).strip()
            if s and profile_mod.normalize_key(s) not in existing:
                existing.add(profile_mod.normalize_key(s))
                extracted[key].append(s)
    if new.get("style_sample"):
        extracted["style_samples"].append(new["style_sample"])
    return extracted


def _merge(extracted: dict, new: dict | None) -> dict:
    return merge_extracted(extracted, new)


def _ask_question(session: Session, llm: LLMClient, interview: Interview) -> str:
    # 「开口说话」类 prompt 注入口语风格指南（见 replicant/style.py）
    system = speak_system("你是一个温和的人格访谈员，根据指定访谈阶段生成下一个问题，只输出问题本身。")
    user = f"TASK:interview_question\nSTAGE:{interview.stage}\nROUND:{interview.stage_round}"
    question = llm.complete(system, user).strip()
    session.add(InterviewTurn(interview_id=interview.id, role="agent", text=question, stage=interview.stage))
    log_message(session, "interview", interview.id, "clone", question)
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
    log_message(session, "interview", interview.id, "user", text)

    # LLM 抽取结构化信息（只负责填空，不做决策）
    extract_prompt = (
        f"TASK:extract\nSTAGE:{interview.stage}\n"
        f"{EXTRACT_CONTRACT.format(stage=interview.stage)}\n用户回答：{text}"
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


def handle_reply_stream(session: Session, llm: LLMClient, interview_id: int, text: str) -> Iterator[tuple[str, object]]:
    """流式推进：status（抽取）→ status（想问题）→ delta* → done（载荷与同步返回相同）。

    副作用与 handle_reply 完全一致；done 后客户端拿到的结构与 JSON 接口相同。
    """
    interview = session.get(Interview, interview_id)
    if interview is None:
        yield ("error", f"访谈 {interview_id} 不存在")
        return
    if interview.status == "done":
        yield ("done", {"status": "done", "clone_id": interview.clone_id, "question": None, "stage": None})
        return

    session.add(InterviewTurn(interview_id=interview.id, role="user", text=text, stage=interview.stage))
    log_message(session, "interview", interview.id, "user", text)

    yield ("status", "正在记下你说的…")
    extract_prompt = (
        f"TASK:extract\nSTAGE:{interview.stage}\n"
        f"{EXTRACT_CONTRACT.format(stage=interview.stage)}\n用户回答：{text}"
    )
    new_info = parse_json_loose(llm.complete("你是信息抽取器，只输出 JSON。", extract_prompt))
    extracted = _merge(_extracted(interview), new_info)
    interview.extracted_json = json.dumps(extracted, ensure_ascii=False)

    interview.stage_round += 1
    if protocol.should_advance(interview.stage, interview.stage_round, text):
        nxt = protocol.next_stage(interview.stage)
        if nxt is None:
            yield ("done", _finish(session, llm, interview, extracted))
            return
        interview.stage = nxt
        interview.stage_round = 0

    yield ("status", "正在想接下来问你什么…")
    system = speak_system("你是一个温和的人格访谈员，根据指定访谈阶段生成下一个问题，只输出问题本身。")
    user_prompt = f"TASK:interview_question\nSTAGE:{interview.stage}\nROUND:{interview.stage_round}"
    chunks: list[str] = []
    for kind, payload in llm.chat_stream([
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]):
        if kind == "content":
            chunks.append(payload)
        yield (kind, payload)
    question = "".join(chunks).strip()
    if not question:  # 流完全无输出时退回同步兜底（_ask_question 内部已记录本轮提问）
        question = _ask_question(session, llm, interview)
        yield ("content", question)
    else:
        session.add(InterviewTurn(interview_id=interview.id, role="agent", text=question, stage=interview.stage))
        log_message(session, "interview", interview.id, "clone", question)  # 流式只在 done 时整条落库
    session.commit()
    yield ("done", {"status": "active", "stage": interview.stage, "question": question, "clone_id": None})


def _finish(session: Session, llm: LLMClient, interview: Interview, extracted: dict) -> dict:
    """访谈收敛：落库 Clone + PersonaProfile v1。"""
    clone = Clone(name=extracted["name"] or interview.owner_name)
    session.add(clone)
    session.flush()
    profile_mod.create_initial_profile(
        session,
        clone_id=clone.id,
        name=clone.name,
        traits=extracted["traits"][:10],
        values=extracted["values"][:10],
        facts=extracted["facts"][:30],
        style_samples=extracted["style_samples"][:10],
        diff_reason="访谈收敛，建立初始人格档案 v1",
        source="interview",
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
