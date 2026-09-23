"""FastAPI 入口工厂：挂载路由与静态单页前端。

启动：uvicorn replicant.asgi:app（asgi.py 里的模块级 app 会同时加载预制档案）
环境变量见 config.py；未配置真实 LLM 时自动使用 MockLLM 演示全链路。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel

from .api import clone_api, interview_api, session_api, sim_api
from .config import Settings
from .db import Session, make_engine
from .llm import LLMClient, build_llm
from .presets import seed_presets

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(
    llm: LLMClient | None = None, db_url: str | None = None, load_presets: bool = False
) -> FastAPI:
    """应用工厂：测试可注入 MockLLM 与内存库（测试默认不加载预制档案）。"""
    settings = Settings.from_env()
    engine = make_engine(db_url or settings.db_url)
    SQLModel.metadata.create_all(engine)
    llm = llm or build_llm(settings)

    if load_presets:
        # 启动时幂等加载 presets/：已有同名克隆则跳过，不动已有数据
        with Session(engine) as session:
            seed_presets(session, llm)

    app = FastAPI(title="复制人 Replicant", version="0.1.0")
    app.state.engine = engine
    app.state.llm = llm

    app.include_router(interview_api.router)
    app.include_router(clone_api.router)
    app.include_router(session_api.router)
    app.include_router(sim_api.router)

    # 单页前端（API 路由在前，静态页兜底挂到根路径）
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


# 说明：模块级 ASGI 对象在 replicant/asgi.py（避免 import replicant.main 就建库/连真实 LLM）。
