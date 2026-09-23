"""环境变量配置。

约定：
- REPLICANT_LLM_BASE_URL / REPLICANT_LLM_API_KEY / REPLICANT_LLM_MODEL：
  OpenAI 兼容接口（可接内网 LiteLLM、本地 Ollama 等）。
- REPLICANT_LLM_MOCK=1：强制使用 MockLLM（无网演示、测试）。
- REPLICANT_DB_URL：SQLAlchemy 连接串，默认项目根下的 replicant.db。
- REPLICANT_AUTO_FINALIZE_MSGS：即时聊天自动定型阈值（消息数，0=关闭，默认 0）。
- REPLICANT_PII_BLOCKED_WORDS：PII 过滤的自定义屏蔽词，逗号分隔。
- REPLICANT_OPENAI_DEFAULT_CLONE：OpenAI 兼容接口的默认克隆（id 或 clone-<id>/clone-name:<名>）。

配置优先从项目根目录的 `.env` 读取（KEY=VALUE 每行一项，`#` 开头为注释）；
环境变量优先于 `.env`。`.env` 已在 .gitignore 中，绝不提交。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_TRUE = {"1", "true", "yes", "on"}
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """极简 .env 解析：仅回填未设置的环境变量，不引入第三方依赖。"""
    path = _PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_mock: bool = False
    db_url: str = "sqlite:///replicant.db"

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        return cls(
            llm_base_url=os.getenv("REPLICANT_LLM_BASE_URL") or None,
            llm_api_key=os.getenv("REPLICANT_LLM_API_KEY") or None,
            llm_model=os.getenv("REPLICANT_LLM_MODEL") or None,
            llm_mock=os.getenv("REPLICANT_LLM_MOCK", "").lower() in _TRUE,
            db_url=os.getenv("REPLICANT_DB_URL", "sqlite:///replicant.db"),
        )
