"""聊天记录解析器：宽容地解析聊天导出文本。

至少支持三种格式（时间乱序不影响解析，时间戳会被忽略）：
1. ``[2024-01-01 10:00] 昵称: 内容``
2. ``昵称 2024-01-01 10:00`` 换行后 ``内容``（可跨多行）
3. ``昵称: 内容``

匹配不到任何模式的行会被当作上一条消息的续行内容。
"""

from __future__ import annotations

import re

# [时间] 昵称: 内容
_RE_BRACKET = re.compile(r"^\[([^\]]{4,40})\]\s*([^\s:：，]{1,20})\s*[:：]\s*(.*)$")
# 昵称 2024-01-01 10:00 / 昵称 10:30（换行后是内容）
_RE_HEADER = re.compile(
    r"^([^\s:：，]{1,20})\s+(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?|\d{1,2}[:：]\d{2}(?::\d{2})?)\s*$"
)
# 昵称: 内容
_RE_COLON = re.compile(r"^([^\s:：，]{1,20})\s*[:：]\s*(.+)$")


class NoOwnerMessageError(ValueError):
    """整段记录里没有本人消息。"""


def parse_chatlog(text: str) -> list[dict]:
    """解析聊天导出文本，返回 [{speaker, content, time}]，保持原始顺序。"""
    messages: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _RE_BRACKET.match(line)
        if m:
            current = {"speaker": m.group(2).strip(), "content": m.group(3).strip(), "time": m.group(1).strip()}
            messages.append(current)
            continue
        m = _RE_HEADER.match(line)
        if m:
            current = {"speaker": m.group(1).strip(), "content": "", "time": m.group(2).strip()}
            messages.append(current)
            continue
        m = _RE_COLON.match(line)
        if m:
            current = {"speaker": m.group(1).strip(), "content": m.group(2).strip(), "time": None}
            messages.append(current)
            continue
        # 续行：并入上一条消息
        if current is not None:
            current["content"] = (current["content"] + "\n" + line.strip()).strip()
    return [m for m in messages if m["content"]]


def owner_messages(text: str, alias: str) -> list[dict]:
    """只取本人（alias）的消息；一条都没有则抛 NoOwnerMessageError。"""
    mine = [m for m in parse_chatlog(text) if m["speaker"] == alias]
    if not mine:
        raise NoOwnerMessageError(f"聊天记录中没有找到“{alias}”的消息，请确认本人昵称是否正确")
    return mine
