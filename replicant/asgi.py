"""ASGI 入口：`uvicorn replicant.asgi:app`。

模块级 app 放这里而不是 main.py，避免 import replicant.main（比如测试）时
就建库、加载预制档案、连接真实 LLM。
"""

from .main import create_app

app = create_app(load_presets=True)
