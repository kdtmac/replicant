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
            f"TASK:batch_extract\n本人昵称:{alias}\n本人消息：\n" + "\n".join(contents),
        )
    ) or {}
    facts = [str(x) for x in data.get("facts") or []]
    traits = [str(x) for x in data.get("traits") or []]
    values = [str(x) for x in data.get("values") or []]

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
