"""记忆流：recency + importance + relevance 三因子加权检索，定期反思。

借鉴斯坦福 Generative Agents：
  score = α·recency + β·importance + γ·relevance
- recency：以自增 id 作为时间序，按指数衰减 0.95 ** (最新 id - 本 id)；
- importance：写入时由 LLM 打 1-10 分，检索时归一化到 [0,1]；
- relevance：与查询词的词元重合度（中文字符 + 英文词）。

记忆积累到阈值时触发 reflection：LLM 汇聚近期记忆为高层认知，
存为 importance 9 的 reflection 记忆，并可申请人格 profile patch（新版本）。
反思计数按阈值减量而非清零：批量注入多倍阈值的记忆时会产生多次连续反思，
人格演进不设上限（v1 → v2 → v3 …）。
"""

from __future__ import annotations

import re

from sqlmodel import Session, func, select

from ..db import Clone, Memory
from ..llm import LLMClient, parse_json_loose
from . import profile as profile_mod

# 三因子权重（与 Smallville 同量级，α+β+γ=1）
WEIGHT_RECENCY = 0.3
WEIGHT_IMPORTANCE = 0.4
WEIGHT_RELEVANCE = 0.3
RECENCY_DECAY = 0.95

# 距上次反思积累的贡献计数（聊天+2，对话+1）达到阈值触发一次反思；按阈值减量，多余部分累积到下次
REFLECTION_THRESHOLD = 3

_TOKEN_RE = re.compile(r"[一-鿿]|[a-zA-Z0-9]+")


def tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def relevance(query: str, content: str) -> float:
    """词元重合度，返回 [0,1]。"""
    q = tokens(query)
    if not q:
        return 0.0
    return len(q & tokens(content)) / len(q)


def recency_score(mem_id: int, latest_id: int) -> float:
    return RECENCY_DECAY ** max(latest_id - mem_id, 0)


def add_memory(
    session: Session,
    llm: LLMClient,
    clone_id: int,
    content: str,
    kind: str = "observation",
    importance: int | None = None,
) -> Memory:
    """写入记忆。importance 缺省时由 LLM 打 1-10 分。"""
    if importance is None:
        raw = llm.complete(
            "你是记忆重要性评估器，只为给定记忆内容打 1-10 的整数分，只输出数字。",
            f"TASK:importance\n内容：{content}",
        )
        m = re.search(r"\d+", raw)
        importance = min(10, max(1, int(m.group()) if m else 5))
    memory = Memory(clone_id=clone_id, content=content, kind=kind, importance=importance)
    session.add(memory)
    session.flush()
    return memory


def retrieve(session: Session, clone_id: int, query: str, k: int = 5) -> list[Memory]:
    """按三因子加权分数检索 top-K 记忆。"""
    memories = list(session.exec(select(Memory).where(Memory.clone_id == clone_id)))
    if not memories:
        return []
    latest_id = max(m.id for m in memories)
    scored = [
        (
            WEIGHT_RECENCY * recency_score(m.id, latest_id)
            + WEIGHT_IMPORTANCE * (m.importance / 10)
            + WEIGHT_RELEVANCE * relevance(query, m.content),
            m,
        )
        for m in memories
    ]
    scored.sort(key=lambda item: (-item[0], item[1].id))  # 同分时旧记忆优先（更稳定）
    return [m for _, m in scored[:k]]


def maybe_reflect(session: Session, llm: LLMClient, clone_id: int, allow_patch: bool = True) -> dict | None:
    """达到阈值则触发一次反思（计数减量而非清零）；返回反思结果，未触发返回 None。"""
    clone = session.get(Clone, clone_id)
    if clone is None or clone.since_reflect < REFLECTION_THRESHOLD:
        return None
    clone.since_reflect -= REFLECTION_THRESHOLD
    memories = list(
        session.exec(select(Memory).where(Memory.clone_id == clone_id).order_by(Memory.id.desc())).fetchall()
    )[:10]
    lines = "\n".join(f"- {m.content}" for m in reversed(memories))
    prompt = (
        f"TASK:reflection\nNAME:{clone.name}\nALLOW_PATCH:{'true' if allow_patch else 'false'}\n"
        "请把以下记忆汇聚为 1-3 条高层认知，判断是否值得纳入人格档案，只输出 JSON："
        '{"insights": ["认知1", ...], "patch": null 或 {"add_trait": "新增特质", "add_value": "新增价值观", '
        '"add_fact": "难忘的事实", "diff_reason": "为什么这次经历值得改档案"}}；'
        "patch 只在确实产生了稳定的新认知时给出，宁可不给。\n记忆：\n"
        f"{lines}"
    )
    data = parse_json_loose(
        llm.complete("你是反思器，把记忆汇聚为高层自我认知，只输出 JSON。", prompt)
    ) or {}

    def _insight_str(x) -> str:
        # 真实模型可能返回 {theme/statement/evidence} 对象，统一取陈述句
        if isinstance(x, dict):
            x = x.get("statement") or x.get("theme") or ""
        return str(x).strip()[:120]

    insights = [s for s in (_insight_str(x) for x in (data.get("insights") or [])) if s][:3] or ["（暂无新认知）"]
    add_memory(
        session,
        llm,
        clone_id=clone_id,
        content="【反思】" + "；".join(insights),
        kind="reflection",
        importance=9,
    )
    patched = False
    if allow_patch and isinstance(data.get("patch"), dict):
        patch = data["patch"]

        def _s(*keys: str) -> str | None:
            """宽松取字符串字段：真实模型可能用 trait/add_trait/traits 等不同键名。"""
            for key in keys:
                v = patch.get(key)
                if isinstance(v, dict):
                    v = v.get("value") or v.get("name")
                if isinstance(v, list):
                    v = v[0] if v else None
                if v:
                    s = str(v).strip()
                    if s:
                        return s[:50]
            return None

        new_version = profile_mod.apply_patch(
            session,
            clone_id,
            add_trait=_s("add_trait", "trait", "traits"),
            add_value=_s("add_value", "value", "values"),
            add_fact=_s("add_fact", "fact", "facts"),
            diff_reason=str(patch.get("diff_reason") or patch.get("reason") or "反思汇聚出新认知")[:200],
        )
        patched = new_version is not None
    session.flush()
    return {"insights": insights, "patched": patched}


def absorb_bulk(session: Session, llm: LLMClient, clone_id: int, contents: list[str], kind: str) -> dict:
    """批量注入记忆（如一次性上传聊天记录），随后连续触发反思直到计数低于阈值。

    保证批量场景同样能把 profile 版本往上堆（v1 → v2 → v3 …，不设上限）。
    """
    clone = session.get(Clone, clone_id)
    if clone is None:
        raise KeyError(f"复制人 {clone_id} 不存在")
    for content in contents:
        add_memory(session, llm, clone_id, content=content, kind=kind)
        clone.since_reflect += 1
    reflections: list[dict] = []
    while clone.since_reflect >= REFLECTION_THRESHOLD:
        result = maybe_reflect(session, llm, clone_id, allow_patch=True)
        if result is not None:
            reflections.append(result)
    session.flush()
    latest = profile_mod.latest_profile(session, clone_id)
    return {
        "memory_count": len(contents),
        "reflection_count": len(reflections),
        "profile_version": latest.version if latest else None,
    }
