"""档案共享：预制档案加载、导入、导出。

- 文件格式 ``replicant-preset@1``（见 ``presets/*.json``）：自描述 JSON，含
  name / personality_line / traits / values / facts / style_samples / memories；
- 启动时按 name 幂等加载预制档案（已有同名克隆则跳过，不动用户数据）；
- 导出：把克隆当前最新 profile + 记忆流打包成同一份格式；
- 导入：创建克隆 + profile v1（source=preset/import）+ 种子记忆注入（照常触发反思）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from .db import Clone, Memory
from .llm import LLMClient
from .persona import memory as memory_mod, profile as profile_mod

FORMAT = "replicant-preset@1"
PRESET_DIR = Path(__file__).resolve().parent.parent / "presets"
MEMORY_KINDS = {"fact", "conversation", "reflection"}


class PresetFormatError(ValueError):
    """档案文件格式不合法。"""


def validate_preset(data: Any) -> dict:
    """校验并规整档案内容；类型不对/缺字段抛 PresetFormatError。"""
    if not isinstance(data, dict):
        raise PresetFormatError("档案必须是一个 JSON 对象")
    name = str(data.get("name") or "").strip()
    if not name:
        raise PresetFormatError("档案缺少 name 字段")

    def str_list(key: str) -> list[str]:
        items = data.get(key) or []
        if not isinstance(items, list):
            raise PresetFormatError(f"字段 {key} 必须是数组")
        return [str(x).strip() for x in items if str(x).strip()]

    memories: list[dict] = []
    for m in data.get("memories") or []:
        if not isinstance(m, dict) or not str(m.get("content", "")).strip():
            raise PresetFormatError("memories 每一项都要是含 content 的对象")
        kind = str(m.get("kind") or "fact")
        memories.append(
            {
                "content": str(m["content"]).strip()[:500],
                "importance": min(10, max(1, int(m.get("importance", 5)))),
                "kind": kind if kind in MEMORY_KINDS else "fact",
            }
        )
    return {
        "format": FORMAT,
        "name": name,
        "personality_line": str(data.get("personality_line") or "").strip(),
        "traits": str_list("traits"),
        "values": str_list("values"),
        "facts": str_list("facts"),
        "style_samples": str_list("style_samples"),
        "memories": memories,
    }


def import_preset(session: Session, llm: LLMClient, data: dict, source: str = "import") -> dict:
    """按规整后的档案建克隆：profile v1 + 种子记忆（记忆凑阈值照常触发反思）。"""
    data = validate_preset(data)
    clone = Clone(name=data["name"])
    session.add(clone)
    session.flush()
    profile_mod.create_initial_profile(
        session,
        clone_id=clone.id,
        name=data["name"],
        traits=data["traits"],
        values=data["values"],
        facts=data["facts"],
        style_samples=data["style_samples"],
        diff_reason=f"档案建档 v1（来源：{'预制' if source == 'preset' else '导入'}）",
        source=source,
    )
    for m in data["memories"]:
        content = m["content"] if m["kind"] != "reflection" else f"【反思】{m['content']}"
        memory_mod.add_memory(session, llm, clone_id=clone.id, content=content, kind=m["kind"], importance=m["importance"])
        clone.since_reflect += 1
    reflections = 0
    while clone.since_reflect >= memory_mod.REFLECTION_THRESHOLD:
        if memory_mod.maybe_reflect(session, llm, clone.id, allow_patch=True) is not None:
            reflections += 1
    session.commit()
    latest = profile_mod.latest_profile(session, clone.id)
    return {
        "clone_id": clone.id,
        "name": clone.name,
        "profile_version": latest.version if latest else None,
        "memories_written": len(data["memories"]),
        "reflections": reflections,
    }


def export_clone(session: Session, clone_id: int) -> dict:
    """把克隆导出为 preset 格式（最新 profile + 全量记忆，记忆 kind 规整到三类）。"""
    clone = session.get(Clone, clone_id)
    if clone is None:
        raise KeyError(f"复制人 {clone_id} 不存在")
    profile = profile_mod.latest_profile(session, clone_id)
    if profile is None:
        raise KeyError(f"复制人 {clone_id} 没有人格档案")
    data = profile_mod.to_dict(profile)
    rows = session.exec(select(Memory).where(Memory.clone_id == clone_id).order_by(Memory.id)).all()
    kind_map = {"conversation": "conversation", "reflection": "reflection"}
    memories = [
        {
            "content": m.content.removeprefix("【反思】") if m.kind == "reflection" else m.content,
            "importance": m.importance,
            "kind": kind_map.get(m.kind, "fact"),
        }
        for m in rows
    ]
    traits = data["traits"]
    line = f"{clone.name}：{('、'.join(traits[:3]) + '的人') if traits else '人格还在生长中'}"
    return {
        "format": FORMAT,
        "name": clone.name,
        "personality_line": line,
        "traits": data["traits"],
        "values": data["values"],
        "facts": data["facts"],
        "style_samples": data["style_samples"],
        "memories": memories,
    }


def seed_presets(session: Session, llm: LLMClient, preset_dir: Path | None = None) -> dict:
    """启动时加载 presets/：按 name 幂等（已有同名克隆则跳过）。"""
    directory = preset_dir or PRESET_DIR
    loaded, skipped = 0, 0
    existing = {c.name for c in session.exec(select(Clone)).all()}
    for path in sorted(directory.glob("*.json")):
        try:
            data = validate_preset(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, PresetFormatError):
            continue  # 坏文件跳过，不影响启动
        if data["name"] in existing:
            skipped += 1
            continue
        import_preset(session, llm, data, source="preset")
        existing.add(data["name"])
        loaded += 1
    return {"loaded": loaded, "skipped": skipped}
