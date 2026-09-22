"""FastAPI 入口：挂载路由与静态单页前端。

启动：uvicorn replicant.main:app --reload
环境变量见 config.py；未配置真实 LLM 时自动使用 MockLLM 演示全链路。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel

from .api import clone_api, interview_api, sim_api
from .config import Settings
from .db import make_engine
from .llm import LLMClient, build_llm

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(llm: LLMClient | None = None, db_url: str | None = None) -> FastAPI:
    """应用工厂：测试可注入 MockLLM 与内存库。"""
    settings = Settings.from_env()
    engine = make_engine(db_url or settings.db_url)
    SQLModel.metadata.create_all(engine)

    app = FastAPI(title="复制人 Replicant", version="0.1.0")
    app.state.engine = engine
    app.state.llm = llm or build_llm(settings)

    app.include_router(interview_api.router)
    app.include_router(clone_api.router)
    app.include_router(sim_api.router)

    # 单页前端（API 路由在前，静态页兜底挂到根路径）
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
