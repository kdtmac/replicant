"""SSE 工具：把引擎生成器的事件流转成 text/event-stream 响应。

事件约定：
- ``event: status`` —— 纯文本状态（如"正在回忆你之前说过的事…"）
- ``event: reasoning`` —— thinking 模型的思考增量（纯文本）
- ``event: delta`` —— 正文增量（纯文本）
- ``event: done`` —— 最终完整 JSON（与该接口的同步版返回值一致）
- ``event: error`` —— 错误信息

所有 data 载荷都 JSON 编码成单行，前端统一 JSON.parse 后使用，天然规避
SSE data 行里的多行文本与 UTF-8 碎字问题（HTTP 层按 chunk 到达，由解码器拼字节）。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from fastapi.responses import StreamingResponse


def sse(events: Iterable[tuple[str, Any]]) -> StreamingResponse:
    async def gen():
        try:
            for kind, payload in events:
                name = "delta" if kind == "content" else kind
                yield f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:  # 引擎内部异常也要让前端收得到
            yield f"event: error\ndata: {json.dumps(str(exc), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
