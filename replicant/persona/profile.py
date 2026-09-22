"""人格档案：traits / values / facts / style_samples，显式版本化。

每次更新都是新版本行 + diff_reason，绝不就地修改，保证人格演进可审计。
另提供特质/价值观的轻量规范化去重（纯字符串处理，无第三方依赖）：
"工作与生活平衡" 与 "工作生活平衡" 视为同义，保留首次出现的写法。
"""

from __future__ import annotations

import json
import re

from sqlmodel import Session, desc, select

from ..db import PersonaProfile

# 规范化时忽略的差异：空白、连字符、斜杠、顿号、间隔号、破折号，以及连接词“与/和”
# （"工作与生活平衡" 与 "工作生活平衡" 这类仅连接字不同的写法视为同一特质）
_NORM_SEP = re.compile(r"[\s\-_/、·—–]+")
_NORM_JOINER = re.compile(r"[与和]")


def normalize_key(text: str) -> str:
    """比较用归一化键：去掉空白、连接符号与“与/和”后小写。"""
    return _NORM_JOINER.sub("", _NORM_SEP.sub("", str(text))).lower()


def dedupe_keep_first(items: list[str]) -> list[str]:
    """按归一化键去重，保留首次出现的写法与顺序。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = str(item).strip()
        key = normalize_key(s)
        if s and key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def to_dict(profile: PersonaProfile) -> dict:
    return {
        "clone_id": profile.clone_id,
        "version": profile.version,
        "name": profile.name,
        "traits": json.loads(profile.traits_json),
        "values": json.loads(profile.values_json),
        "facts": json.loads(profile.facts_json),
        "style_samples": json.loads(profile.style_samples_json),
        "source": profile.source,
        "diff_reason": profile.diff_reason,
        "created_at": profile.created_at,
    }


def create_initial_profile(
    session: Session,
    clone_id: int,
    name: str,
    traits: list[str] | None = None,
    values: list[str] | None = None,
    facts: list[str] | None = None,
    style_samples: list[str] | None = None,
    diff_reason: str | None = None,
    source: str = "interview",
) -> PersonaProfile:
    profile = PersonaProfile(
        clone_id=clone_id,
        version=1,
        name=name,
        traits_json=json.dumps(dedupe_keep_first(traits or []), ensure_ascii=False),
        values_json=json.dumps(dedupe_keep_first(values or []), ensure_ascii=False),
        facts_json=json.dumps(facts or [], ensure_ascii=False),
        style_samples_json=json.dumps(style_samples or [], ensure_ascii=False),
        source=source,
        diff_reason=diff_reason,
    )
    session.add(profile)
    session.flush()
    return profile


def latest_profile(session: Session, clone_id: int) -> PersonaProfile | None:
    return session.exec(
        select(PersonaProfile).where(PersonaProfile.clone_id == clone_id).order_by(desc(PersonaProfile.version))
    ).first()


def apply_patch(
    session: Session,
    clone_id: int,
    *,
    add_trait: str | None = None,
    add_value: str | None = None,
    add_fact: str | None = None,
    diff_reason: str,
    source: str = "reflection",
) -> PersonaProfile | None:
    """基于最新版本复制一份并应用补丁，版本号 +1。

    若补丁去重后不产生任何变化，则不创建新版本（返回 None），避免空演进。
    """
    current = latest_profile(session, clone_id)
    if current is None:
        raise KeyError(f"clone {clone_id} 没有人格档案")
    data = to_dict(current)
    changed = False
    # 归一化比较：与已有项仅符号差异（如 "工作生活平衡" vs "工作与生活平衡"）时视为重复
    existing_traits = {normalize_key(t) for t in data["traits"]}
    if add_trait and normalize_key(add_trait) not in existing_traits:
        data["traits"].append(add_trait.strip())
        changed = True
    existing_values = {normalize_key(v) for v in data["values"]}
    if add_value and normalize_key(add_value) not in existing_values:
        data["values"].append(add_value.strip())
        changed = True
    if add_fact and add_fact not in data["facts"]:
        data["facts"].append(add_fact)
        changed = True
    if not changed:
        return None
    profile = PersonaProfile(
        clone_id=clone_id,
        version=current.version + 1,
        name=data["name"],
        traits_json=json.dumps(dedupe_keep_first(data["traits"]), ensure_ascii=False),
        values_json=json.dumps(dedupe_keep_first(data["values"]), ensure_ascii=False),
        facts_json=json.dumps(data["facts"], ensure_ascii=False),
        style_samples_json=json.dumps(data["style_samples"], ensure_ascii=False),
        source=source,
        diff_reason=diff_reason,
    )
    session.add(profile)
    session.flush()
    return profile


def history(session: Session, clone_id: int) -> list[PersonaProfile]:
    return list(
        session.exec(select(PersonaProfile).where(PersonaProfile.clone_id == clone_id).order_by(PersonaProfile.version))
    )
