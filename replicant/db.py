"""SQLModel 表定义与引擎工具。

所有 JSON 列表字段以字符串存库，避免引入额外类型转换。
"""

from __future__ import annotations

import time
from typing import Iterator

from fastapi import Request
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine


# ---------- 表定义 ----------


class Interview(SQLModel, table=True):
    """一次访谈会话（状态机状态持久化在表中，引擎无状态）。"""

    id: int | None = Field(default=None, primary_key=True)
    owner_name: str
    stage: str = "intro"
    stage_round: int = 0
    status: str = "active"  # active / done
    extracted_json: str = "{}"  # 各阶段抽取出的结构化信息
    clone_id: int | None = None
    created_at: float = Field(default_factory=time.time)


class InterviewTurn(SQLModel, table=True):
    """访谈中的一轮对话。"""

    id: int | None = Field(default=None, primary_key=True)
    interview_id: int = Field(foreign_key="interview.id", index=True)
    role: str  # agent（提问）/ user（回答）
    text: str
    stage: str
    created_at: float = Field(default_factory=time.time)


class Clone(SQLModel, table=True):
    """一个复制人。"""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    since_reflect: int = 0  # 距上次反思积累的贡献计数，达到阈值触发 reflection
    created_at: float = Field(default_factory=time.time)


class PersonaProfile(SQLModel, table=True):
    """人格档案（显式版本化：每次更新存新版本 + diff 原因）。"""

    id: int | None = Field(default=None, primary_key=True)
    clone_id: int = Field(foreign_key="clone.id", index=True)
    version: int = 1
    name: str = ""
    traits_json: str = "[]"
    values_json: str = "[]"
    facts_json: str = "[]"
    style_samples_json: str = "[]"
    diff_reason: str | None = None  # 相对上一版本的变更原因，v1 为 None
    created_at: float = Field(default_factory=time.time)


class Memory(SQLModel, table=True):
    """记忆流条目（借鉴 Smallville：importance 1-10，检索用三因子加权）。"""

    id: int | None = Field(default=None, primary_key=True)
    clone_id: int = Field(foreign_key="clone.id", index=True)
    content: str
    kind: str = "observation"  # interview / chat / conversation / observation / reflection
    importance: int = 5
    created_at: float = Field(default_factory=time.time)
    # recency 直接用自增 id 代表“时间远近”，保证测试确定性


class SimState(SQLModel, table=True):
    """模拟世界状态（单行，id 恒为 1）。"""

    id: int = Field(default=1, primary_key=True)
    tick: int = 0


class SimEvent(SQLModel, table=True):
    """模拟世界时间线事件。"""

    id: int | None = Field(default=None, primary_key=True)
    tick: int
    kind: str  # dialogue / action / profile_patch / notice
    actors_json: str = "[]"
    description: str
    created_at: float = Field(default_factory=time.time)


# ---------- 引擎与会话依赖 ----------


def make_engine(db_url: str):
    kwargs: dict = {}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if db_url in ("sqlite://", "sqlite:///:memory:"):
            # 内存库需要静态连接池，否则每个 session 都是不同的库
            kwargs["poolclass"] = StaticPool
    return create_engine(db_url, **kwargs)


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def get_llm(request: Request):
    return request.app.state.llm
