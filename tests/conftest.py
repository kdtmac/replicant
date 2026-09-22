"""测试公共夹具：内存库 + MockLLM，不依赖网络。"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel

from replicant.db import make_engine
from replicant.llm import MockLLM


@pytest.fixture()
def llm():
    return MockLLM()


@pytest.fixture()
def session():
    engine = make_engine("sqlite://")  # 内存库 + StaticPool
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
