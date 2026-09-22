"""LLM 抽象：协议 + OpenAI 兼容实现 + 确定性 MockLLM。

所有下游模块都在 prompt 第一行写 ``TASK:<任务名>`` 标记，
MockLLM 靠这些标记返回确定性内容，因此单元测试与无网演示不依赖真实模型；
真实模型下这些标记只是无害的指令文本。
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from .config import Settings


# ---------- 协议 ----------


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


def parse_json_loose(text: str):
    """从 LLM 输出中宽松地提取第一个 JSON 对象/数组。"""
    for start, end in (("{", "}"), ("[", "]")):
        i, j = text.find(start), text.rfind(end)
        if i != -1 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                continue
    return None


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_mock or not (settings.llm_base_url and settings.llm_model):
        return MockLLM()
    return OpenAILLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "EMPTY",
        model=settings.llm_model,
    )


# ---------- OpenAI 兼容实现 ----------


class OpenAILLM:
    def __init__(self, base_url: str, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,
        )
        return resp.choices[0].message.content or ""


# ---------- MockLLM ----------


def _marker(text: str, name: str) -> str | None:
    m = re.search(rf"^{name}:(.*)$", text, re.M)
    return m.group(1).strip() if m else None


# 访谈题库：每个阶段一组备选问题，按已答轮数轮换
QUESTION_BANK: dict[str, list[str]] = {
    "intro": ["你好，我是你的访谈员。先做个自我介绍吧——你叫什么名字，怎么称呼你比较好？"],
    "life_story": [
        "聊聊你的成长经历吧：你在哪里长大，有什么对你影响很深的转折点？",
        "如果再说一个对你影响最大的人或一段经历，会是什么？",
    ],
    "values": [
        "你最看重什么？有没有什么事是你宁愿吃亏也不愿去做的？",
        "想象十年后回头看，你希望自己一直坚持了什么原则？",
    ],
    "habits": ["描述一个你普通的工作日：早上通常几点起，空闲的时候喜欢做什么？"],
    "style_sampling": [
        "给我演示一下：朋友跟你抱怨工作不顺，你会怎么安慰他？就用你平时的口吻说。",
        "再换一个场景：用你自己的话吐槽一下最近的天气。",
    ],
}

STAGE_LABEL = {
    "intro": "自我介绍",
    "life_story": "人生故事",
    "values": "价值观",
    "habits": "日常习惯",
    "style_sampling": "语言风格",
}

TRAIT_KEYWORDS = ["开朗", "内向", "乐观", "悲观", "认真", "随和", "幽默", "固执", "敏感", "自律", "热情", "冷静"]
VALUE_KEYWORDS = ["家庭", "自由", "事业", "朋友", "健康", "金钱", "知识", "快乐", "诚实", "公平", "热爱"]
IMPORTANT_KEYWORDS = ["重要", "重大", "转折", "改变", "成就", "失去"]
LOCATIONS = ["公园", "街角咖啡馆", "社区图书馆", "河边步道"]


class MockLLM:
    """无网环境可用的确定性 LLM，按 TASK 标记分派到固定套路。

    ``calls`` 记录了全部 (system, user)，测试可用来检查 prompt 组装内容。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        task = _marker(user, "TASK") or ""
        handler = {
            "interview_question": self._interview_question,
            "extract": self._extract,
            "importance": self._importance,
            "chat": self._chat,
            "plan": self._plan,
            "social_turn": self._social_turn,
            "reflection": self._reflection,
        }.get(task)
        return handler(user) if handler else "（MockLLM：未识别的任务）"

    # --- 各任务套路 ---

    def _interview_question(self, user: str) -> str:
        stage = _marker(user, "STAGE") or "intro"
        round_no = int(_marker(user, "ROUND") or 0)
        bank = QUESTION_BANK.get(stage, QUESTION_BANK["intro"])
        return bank[round_no % len(bank)]

    def _extract(self, user: str) -> str:
        stage = _marker(user, "STAGE") or "intro"
        m = re.search(r"用户回答：(.*)$", user, re.S)
        answer = (m.group(1).strip() if m else "") or "（无）"
        facts: list[str] = [f"（{STAGE_LABEL.get(stage, stage)}）{answer[:80]}"]
        result: dict = {
            "facts": facts,
            "traits": [kw for kw in TRAIT_KEYWORDS if kw in answer],
            "values": [kw for kw in VALUE_KEYWORDS if kw in answer],
            "name": None,
            "style_sample": None,
        }
        name_m = re.search(r"我叫([\w·一-鿿]{1,10})", answer) or re.search(r"我是([\w·一-鿿]{1,10})", answer)
        if stage == "intro" and name_m:
            result["name"] = name_m.group(1)
            facts.append(f"用户自称“{result['name']}”")
        if stage == "style_sampling":
            result["style_sample"] = answer[:120]
        return json.dumps(result, ensure_ascii=False)

    def _importance(self, user: str) -> str:
        m = re.search(r"内容：(.*)$", user, re.S)
        content = m.group(1).strip() if m else ""
        if any(kw in content for kw in IMPORTANT_KEYWORDS):
            return "9"
        return str(len(content) % 5 + 3)  # 3-7，确定性

    def _chat(self, user: str) -> str:
        name = _marker(user, "NAME") or "复制人"
        m = re.search(r"^用户：(.*?)$", user, re.M)
        msg = (m.group(1) if m else "").strip() or "你好"
        return f"（{name}）嗯……说到「{msg[:24]}」，我倒觉得吧，日子总得往前过，这事儿不用太往心里去。"

    def _plan(self, user: str) -> str:
        name = _marker(user, "NAME") or "某人"
        tick = int(_marker(user, "TICK") or 0)
        loc = LOCATIONS[tick % len(LOCATIONS)]
        return f"{name}决定去{loc}散散步，边走边想想最近发生的事。"

    def _social_turn(self, user: str) -> str:
        name = _marker(user, "NAME") or "甲"
        partner = _marker(user, "PARTNER") or "乙"
        loc = _marker(user, "LOCATION") or "公园"
        return f"{name}：「{partner}，好久不见！我刚在{loc}这边转了转，最近过得怎么样？」"

    def _reflection(self, user: str) -> str:
        name = _marker(user, "NAME") or "复制人"
        allow_patch = (_marker(user, "ALLOW_PATCH") or "false") == "true"
        memories = [line.strip("- ").strip() for line in user.splitlines() if line.startswith("- ")]
        first = (memories[0][:40] if memories else "最近的经历")
        patch = None
        if allow_patch:
            patch = {
                "add_trait": "善于从社会交往中反思",
                "diff_reason": "模拟社会中的反思汇聚出新认知，纳入人格档案",
            }
        return json.dumps(
            {
                "insights": [f"{name}意识到：「{first}…」这类经历正悄悄塑造着自己"],
                "patch": patch,
            },
            ensure_ascii=False,
        )
