"""上传聊天记录快速生成 + 无限迭代测试：多次批量记忆注入持续推高 profile 版本。"""

from __future__ import annotations

import pytest

from replicant.chatlog_parser import NoOwnerMessageError
from replicant.db import Clone
from replicant.persona import profile as profile_mod
from replicant.timeline import build_timeline
from replicant.upload import create_clone_from_upload

WECHAT_STYLE = """[2024-03-01 09:12] 阿芳: 早啊，昨晚睡得好吗
[2024-03-01 09:13] 阿明: 还行，我一般是十一点睡七点起，雷打不动
[2024-03-01 09:14] 阿芳: 你真自律
[2024-03-01 09:15] 阿明: 哈哈大家都说我很自律，其实我也就是坚持
[2024-02-25 20:01] 阿明: 工作再忙我也得抽时间陪家人，家庭最重要
[2024-02-25 20:03] 阿芳: 嗯嗯，家和万事兴
[2024-02-20 14:00] 阿明: 钱够花就行，我最看重的还是健康和家庭
[2024-02-20 14:02] 阿明: 对了周末去爬山吗，我最近迷上徒步了
[2024-02-18 11:30] 阿芳: 你说话总是很乐观
[2024-02-18 11:31] 阿明: 哈哈，别慌，天塌不下来，慢慢来
"""


def test_upload_creates_clone_v1(session, llm):
    result = create_clone_from_upload(session, llm, WECHAT_STYLE, alias="阿明", owner_name="阿明")
    assert result["owner_messages"] == 6
    clone = session.get(Clone, result["clone_id"])
    assert clone.name == "阿明"
    profile = profile_mod.latest_profile(session, clone.id)
    assert profile.version >= 1
    v1 = profile_mod.history(session, clone.id)[0]
    assert v1.version == 1 and v1.source == "upload"
    assert "自律" in v1.traits_json
    assert "家庭" in v1.values_json
    # 风格样本使用本人原句
    assert any("别慌，天塌不下来" in line for line in WECHAT_STYLE.splitlines())
    import json as _json

    samples = _json.loads(v1.style_samples_json)
    contents = [m.split(": ", 1)[-1] for m in WECHAT_STYLE.splitlines() if m.startswith("[") and "阿明:" in m]
    assert all(s in contents for s in samples)


def test_upload_no_owner_message_422(session, llm):
    from replicant.chatlog_parser import owner_messages

    with pytest.raises(NoOwnerMessageError):
        owner_messages(WECHAT_STYLE, "不存在的昵称")


def test_bulk_upload_triggers_multiple_patches_no_cap(session, llm):
    """批量上传一次性注入大量记忆 → 连续多次反思 → v1 → v2 → v3…（证明无封顶）。"""
    result = create_clone_from_upload(session, llm, WECHAT_STYLE, alias="阿明")
    clone_id = result["clone_id"]
    assert result["memories_written"] == 6
    versions = profile_mod.history(session, clone_id)
    # 7 条消息 + 批量注入触发的多次反思：版本必须一路递增且超过 v2
    assert versions[0].version == 1
    assert versions[-1].version >= 3
    assert [v.version for v in versions] == list(range(1, versions[-1].version + 1))
    assert all(v.source == "reflection" for v in versions[1:])

    # 再上传一段新记录，版本继续往上堆
    more = "阿明: 最近开始学习摄影了\n阿芳: 牛的\n阿明: 哈哈只是想记录生活\n"
    create_clone_from_upload(session, llm, more, alias="阿明", owner_name="阿明")  # 新克隆，不影响原版本
    # 直接对原克隆追加批量记忆（等价于“再上传新聊天记录”往该克隆记忆流里长）
    from replicant.persona import memory as memory_mod

    before = profile_mod.latest_profile(session, clone_id).version
    memory_mod.absorb_bulk(
        session, llm, clone_id,
        ["（聊天导出）最近开始学习摄影", "（聊天导出）只是想记录生活", "（聊天导出）周末又去了河边徒步"],
        kind="upload",
    )
    assert profile_mod.latest_profile(session, clone_id).version > before


def test_timeline_merges_versions_memories_events(session, llm):
    result = create_clone_from_upload(session, llm, WECHAT_STYLE, alias="阿明")
    clone_id = result["clone_id"]
    items = build_timeline(session, clone_id)
    types = {i["type"] for i in items}
    assert "profile_version" in types and "memory" in types
    versions = [i for i in items if i["type"] == "profile_version"]
    assert versions[0]["source"] == "upload"
    # 时间线按时间排序
    ts = [i["ts"] for i in items]
    assert ts == sorted(ts)
