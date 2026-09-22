"""SSE 流式接口测试：事件序列 status → (reasoning|delta)* → done，MockLLM 驱动。

同时验证 done 载荷与同步 JSON 接口返回结构一致（向后兼容）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from replicant.llm import MockLLM
from replicant.main import create_app


@pytest.fixture()
def client():
    app = create_app(llm=MockLLM(), db_url="sqlite://")
    return TestClient(app)


def _collect_sse(resp) -> list[tuple[str, object]]:
    """把 SSE 原始文本解析成 [(event, data)]；data 统一 JSON 解码。"""
    resp.read()  # 流式响应需先读尽内容
    assert resp.headers["content-type"].startswith("text/event-stream")
    events: list[tuple[str, object]] = []
    for block in resp.text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines.get("event", ""), json.loads(lines["data"])))
    return events


def test_clone_chat_stream_event_sequence(client):
    clone = client.post("/clones/quick", json={"name": "阿明", "traits": ["随和"]}).json()
    with client.stream("POST", f"/clones/{clone['clone_id']}/chat/stream", json={"message": "在吗"}) as resp:
        events = _collect_sse(resp)

    names = [n for n, _ in events]
    # 事件序列：status, status, reasoning（可多个）, delta（≥1 块）, done
    assert names[:2] == ["status", "status"]
    assert "reasoning" in names
    delta_idx = [i for i, n in enumerate(names) if n == "delta"]
    assert len(delta_idx) >= 2  # MockLLM 分块 ≥2
    assert names[-1] == "done"
    assert names.index("done") > max(delta_idx)

    # delta 拼接 = done 里的 reply；done 载荷与同步接口结构一致
    text = "".join(d for n, d in events if n == "delta")
    done = events[-1][1]
    assert done["reply"] == text.strip()
    assert {"clone_id", "reply", "profile_version", "used_memory_ids", "reflected"} <= set(done)
    assert done["clone_id"] == clone["clone_id"]

    # 同步接口回归：结构一致
    sync = client.post(f"/clones/{clone['clone_id']}/chat", json={"message": "再说一句"}).json()
    assert {"clone_id", "reply", "profile_version", "used_memory_ids", "reflected"} <= set(sync)


def test_chat_session_stream(client):
    sid = client.post("/chat-sessions", json={"name": "小测"}).json()["session_id"]
    for i in range(3):
        with client.stream("POST", f"/chat-sessions/{sid}/msg/stream", json={"text": f"第{i+1}句话。"}) as resp:
            events = _collect_sse(resp)
        names = [n for n, _ in events]
        assert names[0] == "status" and names[-1] == "done"
        done = events[-1][1]
        assert done["msg_count"] == i + 1
        assert done["reply"]
    assert done["ready"] is True
    # finalize 后 stream 走克隆聊天路径，done 带 clone 信息
    fin = client.post(f"/chat-sessions/{sid}/finalize").json()
    with client.stream("POST", f"/chat-sessions/{sid}/msg/stream", json={"text": "定型后再聊聊"}) as resp:
        events = _collect_sse(resp)
    done = events[-1][1]
    assert done["status"] == "finalized" and done["clone_id"] == fin["clone_id"]
    assert "profile_version" in done


def test_interview_reply_stream(client):
    iv = client.post("/interviews", json={"owner_name": "流式用户"}).json()
    assert iv["question"]
    with client.stream(
        "POST", f"/interviews/{iv['interview_id']}/reply/stream",
        json={"text": "我叫流式用户，是个开朗的人。"},
    ) as resp:
        events = _collect_sse(resp)
    names = [n for n, _ in events]
    assert names[:2] == ["status", "status"]
    assert names[-1] == "done"
    done = events[-1][1]
    assert done["status"] == "active" and done["stage"] == "life_story"
    assert done["question"] == "".join(d for n, d in events if n == "delta").strip()

    # 同步接口回归
    r2 = client.post(f"/interviews/{iv['interview_id']}/reply", json={"text": "我在小城长大，后来北漂。"}).json()
    assert r2["status"] == "active"


def test_stream_error_event(client):
    with client.stream("POST", "/clones/999/chat/stream", json={"message": "在吗"}) as resp:
        events = _collect_sse(resp)
    assert events[0][0] == "error"
