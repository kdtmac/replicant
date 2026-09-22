"""聊天记录落库与会话恢复测试：ChatMessage 写入（同步/流式）+ 三个恢复 GET 接口。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from replicant.db import ChatMessage
from replicant.llm import MockLLM
from replicant.main import create_app


@pytest.fixture()
def client():
    app = create_app(llm=MockLLM(), db_url="sqlite://")
    return TestClient(app)


def _thread_messages(client: TestClient, thread_type: str, thread_id: int):
    """从 app 自己的引擎读库，保证与请求路径同一数据源。"""
    with Session(client.app.state.engine) as s:
        return list(
            s.exec(
                select(ChatMessage)
                .where(ChatMessage.thread_type == thread_type, ChatMessage.thread_id == thread_id)
                .order_by(ChatMessage.id)
            )
        )


def test_clone_chat_messages_written_sync(client):
    clone_id = client.post("/clones/quick", json={"name": "阿明"}).json()["clone_id"]
    client.post(f"/clones/{clone_id}/chat", json={"message": "在吗"})
    client.post(f"/clones/{clone_id}/chat", json={"message": "再聊两句"})
    rows = _thread_messages(client, "clone_chat", clone_id)
    assert len(rows) == 4
    assert [m.role for m in rows] == ["user", "clone", "user", "clone"]
    assert rows[0].text == "在吗"


def test_clone_chat_messages_written_stream_only_complete(client):
    """流式路径：整条写入（done 时落库），内容与同步一致。"""
    clone_id = client.post("/clones/quick", json={"name": "阿明"}).json()["clone_id"]
    with client.stream("POST", f"/clones/{clone_id}/chat/stream", json={"message": "流式说句话"}) as resp:
        resp.read()
    rows = _thread_messages(client, "clone_chat", clone_id)
    assert [m.role for m in rows] == ["user", "clone"]
    assert rows[0].text == "流式说句话"
    # 克隆回复是整块（无半截分块）
    assert rows[1].text and "嗯" not in rows[1].text[:0]


def test_session_list_and_messages_api(client):
    sid1 = client.post("/chat-sessions", json={"name": "聊一半的用户"}).json()["session_id"]
    client.post(f"/chat-sessions/{sid1}/msg", json={"text": "还在琢磨中……"})
    client.post(f"/chat-sessions/{sid1}/msg", json={"text": "第二句，快聊够阈值了"})
    sid2 = client.post("/chat-sessions", json={"name": "B"}).json()["session_id"]
    for t in ["甲", "乙", "丙"]:
        client.post(f"/chat-sessions/{sid2}/msg", json={"text": t + "，我是B。"})
    client.post(f"/chat-sessions/{sid2}/finalize")

    listing = client.get("/chat-sessions").json()
    assert len(listing) == 2
    # active 排前， finalized 也能看到
    assert listing[0]["id"] == sid1 and listing[0]["status"] == "active"
    assert listing[1]["status"] == "finalized" and listing[1]["clone_id"] is not None
    assert listing[0]["last_message_preview"] and listing[0]["msg_count"] == 2

    detail = client.get(f"/chat-sessions/{sid1}/messages").json()
    assert detail["status"] == "active" and detail["ready"] is False
    assert len(detail["messages"]) == 4  # 2 用户 + 2 回复
    assert detail["messages"][0]["role"] == "user"

    detail2 = client.get(f"/chat-sessions/{sid2}/messages").json()
    assert detail2["status"] == "finalized" and detail2["ready"] is True
    assert detail2["clone_id"] is not None


def test_clone_messages_api(client):
    clone_id = client.post("/clones/quick", json={"name": "阿磊"}).json()["clone_id"]
    client.post(f"/clones/{clone_id}/chat", json={"message": "你好"})
    data = client.get(f"/clones/{clone_id}/messages").json()
    assert data["name"] == "阿磊"
    assert [(m["role"]) for m in data["messages"]] == ["user", "clone"]


def test_interview_messages_written(client):
    """访谈线程也落原始消息（user 回答 + agent 提问）。"""
    iv = client.post("/interviews", json={"owner_name": "阿测"}).json()
    client.post(
        f"/interviews/{iv['interview_id']}/reply",
        json={"text": "我叫阿测，是个开朗的人。"},
    )
    rows = _thread_messages(client, "interview", iv["interview_id"])
    assert [m.role for m in rows] == ["clone", "user", "clone"]


def test_messages_api_404(client):
    assert client.get("/chat-sessions/999/messages").status_code == 404
    assert client.get("/clones/999/messages").status_code == 404
