"""访谈协议：确定性状态机（LLM 不参与推进决策）。

阶段：自我介绍 → 人生故事 → 价值观 → 日常习惯 → 语言风格采样。
收敛判据是简单启发式：
- 达到 min_rounds 且最后一答非空（有效回答），则进入下一阶段；
- 无论如何达到 max_rounds 强制推进，保证终止；
- 回答太短（<3 个有效字符）视为敷衍，不计入有效回答。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageSpec:
    name: str
    label: str
    min_rounds: int
    max_rounds: int


PROTOCOL: list[StageSpec] = [
    StageSpec("intro", "自我介绍", min_rounds=1, max_rounds=2),
    StageSpec("life_story", "人生故事", min_rounds=2, max_rounds=4),
    StageSpec("values", "价值观", min_rounds=2, max_rounds=4),
    StageSpec("habits", "日常习惯", min_rounds=1, max_rounds=3),
    StageSpec("style_sampling", "语言风格采样", min_rounds=2, max_rounds=3),
]

STAGE_INDEX = {spec.name: i for i, spec in enumerate(PROTOCOL)}
MIN_MEANINGFUL_LEN = 3


def get_stage(name: str) -> StageSpec:
    return PROTOCOL[STAGE_INDEX[name]]


def is_meaningful(answer: str) -> bool:
    return len(answer.strip()) >= MIN_MEANINGFUL_LEN


def should_advance(stage: str, stage_round: int, last_answer: str) -> bool:
    """state_round 为当前阶段已完成的回答轮数（含本轮）。"""
    spec = get_stage(stage)
    if stage_round >= spec.max_rounds:
        return True
    return stage_round >= spec.min_rounds and is_meaningful(last_answer)


def next_stage(stage: str) -> str | None:
    idx = STAGE_INDEX[stage]
    return PROTOCOL[idx + 1].name if idx + 1 < len(PROTOCOL) else None
