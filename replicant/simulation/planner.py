"""行动规划：每个复制人的下一步行动（LLM 生成，MockLLM 下确定性）。"""

from __future__ import annotations

from sqlmodel import Session

from ..db import Clone
from ..llm import LLMClient
from ..persona import memory as memory_mod


def plan_action(session: Session, llm: LLMClient, clone: Clone, tick: int) -> str:
    """为单个复制人生成一次独立行动，并写入观察记忆。"""
    prompt = (
        f"TASK:plan\nNAME:{clone.name}\nTICK:{tick}\n"
        f"为{clone.name}生成一条简短的下一步行动（一两句话，含地点）。"
    )
    action = llm.complete("你是行动规划器，只输出行动描述本身。", prompt).strip()
    memory_mod.add_memory(session, llm, clone_id=clone.id, content=f"（tick {tick}）{action}", kind="observation")
    clone.since_reflect += 1
    return action
