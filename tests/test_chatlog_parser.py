"""聊天记录解析器测试：三种格式、时间乱序、无本人消息报错。"""

from __future__ import annotations

import pytest

from replicant.chatlog_parser import NoOwnerMessageError, owner_messages, parse_chatlog


def test_bracket_format():
    text = "[2024-01-01 10:00] 张三: 在吗\n[2024-01-01 10:01] 阿芳: 在的，咋了\n"
    msgs = parse_chatlog(text)
    assert [m["speaker"] for m in msgs] == ["张三", "阿芳"]
    assert msgs[0]["content"] == "在吗"
    assert msgs[0]["time"] == "2024-01-01 10:00"


def test_header_multiline_format():
    """格式2：昵称+时间一行，内容跨多行。"""
    text = "阿明 2024-03-05 21:30\n今天加班到好晚\n真的累\n阿芳 2024-03-05 21:32\n抱抱你\n"
    msgs = parse_chatlog(text)
    assert len(msgs) == 2
    assert msgs[0]["speaker"] == "阿明"
    assert "今天加班到好晚" in msgs[0]["content"] and "真的累" in msgs[0]["content"]
    assert msgs[1]["content"] == "抱抱你"


def test_plain_colon_format():
    text = "阿明: 周末去爬山吗\n阿芳: 去！\n"
    msgs = parse_chatlog(text)
    assert [m["speaker"] for m in msgs] == ["阿明", "阿芳"]
    assert msgs[0]["time"] is None


def test_out_of_order_timestamps():
    """时间乱序不影响解析，保持原始顺序。"""
    text = (
        "[2024-01-05 09:00] 阿明: 第三条\n"
        "[2024-01-01 08:00] 阿明: 第一条\n"
        "[2024-01-03 12:00] 阿芳: 乱序也没事\n"
    )
    mine = owner_messages(text, "阿明")
    assert [m["content"] for m in mine] == ["第三条", "第一条"]


def test_mixed_formats_and_continuation():
    text = (
        "[2024-01-01 10:00] 阿明: 早上好\n"
        "今天天气不错\n"  # 无法匹配的行并入上一条
        "阿芳: 早！\n"
        "阿明 2024-01-01 10:05\n我刚跑完步回来\n"
    )
    msgs = parse_chatlog(text)
    assert msgs[0]["speaker"] == "阿明" and "今天天气不错" in msgs[0]["content"]
    assert msgs[-1]["content"] == "我刚跑完步回来"
    mine = owner_messages(text, "阿明")
    assert len(mine) == 2


def test_no_owner_message_raises():
    with pytest.raises(NoOwnerMessageError, match="不存在的名字"):
        owner_messages("阿明: 你好\n阿芳: 在\n", "不存在的名字")
