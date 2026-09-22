"""上传聊天记录快速生成：解析导出文本 → 只取本人消息 → 批量抽取 → 立即产出克隆 v1。

批量注入本人消息为记忆，自然触发多次 reflection 继续堆版本（无限迭代的一部分）。
"""

from __future__ import annotations

from sqlmodel import Session

from .chatlog_parser import NoOwnerMessageError, owner_messages
from .db import Clone
from .llm import LLMClient, parse_json_loose
from .persona import memory as memory_mod, profile as profile_mod

STYLE_SAMPLE_LIMIT = 5


def create_clone_from_upload(
    session: Session,
    llm: LLMClient,
    text: str,
    alias: str,
    owner_name: str | None = None,
) -> dict:
    mine = owner_messages(text, alias)  # alias 为本人昵称
    contents = [m["content"] for m in mine]

    # 一次 LLM 调用完成批量抽取（MockLLM 下确定性）
    data = parse_json_loose(
        llm.complete(
            "你是信息抽取器，从本人消息中批量抽取人格信息，只输出 JSON。",
            "TASK:batch_extract\n本人昵称:"
            + alias
            + "\n只输出 JSON：facts（事实字符串数组）、traits（性格特质短字符串数组）、"
              "values（价值观短字符串数组）；数组元素必须是纯字符串，不要对象。\n本人消息：\n"
            + "\n".join(contents),
        )
    ) or {}

    def _short_strings(items, limit: int) -> list[str]:
        """真实模型可能返回对象/长句，统一规整为短字符串。"""
        out = []
        for item in items or []:
            if isinstance(item, dict):  # 例如 {category/value/confidence}
                item = item.get("value") or item.get("category") or ""
            s = str(item).strip()
            if s and s not in out:
                out.append(s[:60])
            if len(out) >= limit:
                break
        return out

    facts = _short_strings(data.get("facts"), 20)
    traits = _short_strings(data.get("traits"), 10)
    values = _short_strings(data.get("values"), 10)

    # 风格样本直接用本人原句（取较长的几条更有代表性）
    style_samples = sorted(set(contents), key=len, reverse=True)[:STYLE_SAMPLE_LIMIT]

    clone = Clone(name=owner_name or alias)
    session.add(clone)
    session.flush()
    profile_mod.create_initial_profile(
        session,
        clone_id=clone.id,
        name=clone.name,
        traits=traits,
        values=values,
        facts=facts,
        style_samples=style_samples,
        diff_reason=f"上传聊天记录立即建档 v1（本人消息 {len(mine)} 条）",
        source="upload",
    )
    absorb = memory_mod.absorb_bulk(
        session, llm, clone_id=clone.id,
        contents=[f"（聊天导出）{c[:120]}" for c in contents][:20],
        kind="upload",
    )
    session.commit()
    return {
        "clone_id": clone.id,
        "name": clone.name,
        "owner_messages": len(mine),
        "facts": facts,
        "traits": traits,
        "values": values,
        "style_samples": style_samples,
        "memories_written": absorb["memory_count"],
        "reflections": absorb["reflection_count"],
        "profile_version": absorb["profile_version"],
    }


__all__ = ["create_clone_from_upload", "NoOwnerMessageError"]
