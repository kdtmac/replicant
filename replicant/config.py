"""环境变量配置。

约定：
- REPLICANT_LLM_BASE_URL / REPLICANT_LLM_API_KEY / REPLICANT_LLM_MODEL：
  OpenAI 兼容接口（可接内网 LiteLLM、本地 Ollama 等）。
- REPLICANT_LLM_MOCK=1：强制使用 MockLLM（无网演示、测试）。
- REPLICANT_DB_URL：SQLAlchemy 连接串，默认项目根下的 replicant.db。

未配置齐 LLM 三要素时自动回退到 MockLLM，保证全链路可演示。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE = {"1", "true", "yes", "on"}


@dataclass
class Settings:
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_mock: bool = False
    db_url: str = "sqlite:///replicant.db"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            llm_base_url=os.getenv("REPLICANT_LLM_BASE_URL") or None,
            llm_api_key=os.getenv("REPLICANT_LLM_API_KEY") or None,
            llm_model=os.getenv("REPLICANT_LLM_MODEL") or None,
            llm_mock=os.getenv("REPLICANT_LLM_MOCK", "").lower() in _TRUE,
            db_url=os.getenv("REPLICANT_DB_URL", "sqlite:///replicant.db"),
        )
