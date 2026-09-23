"""敏感信息过滤：上传/聊天文本入库前的合规防线。

纯正则实现、零依赖。每处命中**整段替换**为 ``[已过滤]``（不打码一部分，
防止从上下文拼回）；自定义屏蔽词从 ``REPLICANT_PII_BLOCKED_WORDS`` 读取（逗号分隔）。
"""

from __future__ import annotations

import os
import re

FILTERED = "[已过滤]"

# 中国大陆手机号：11 位、1 开头、第二位 3-9
_RE_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 邮箱
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 身份证 18 位（地址码 6 位 + 出生日期 8 位 + 顺序码 3 位 + 校验码）
_RE_IDCARD = re.compile(
    r"(?<!\d)\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
)
# 银行卡号：13-19 位连续数字（在手机号/身份证之后执行，避免重叠误判）
_RE_BANKCARD = re.compile(r"(?<!\d)\d{13,19}(?!\d)")


def blocked_words() -> list[str]:
    raw = os.getenv("REPLICANT_PII_BLOCKED_WORDS", "")
    return [w.strip() for w in raw.split(",") if w.strip()]


def scrub(text: str, extra_words: list[str] | None = None) -> tuple[str, int]:
    """过滤一段文本，返回 (净化后文本, 命中次数)。每个命中整段替换为 [已过滤]。"""
    if not text:
        return text, 0
    count = 0
    for pattern in (_RE_IDCARD, _RE_PHONE, _RE_EMAIL, _RE_BANKCARD):
        text, n = pattern.subn(FILTERED, text)
        count += n
    for word in extra_words if extra_words is not None else blocked_words():
        n = text.count(word)
        if n:
            text = text.replace(word, FILTERED)
            count += n
    return text, count
