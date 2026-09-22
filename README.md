# 复制人 Replicant

人格克隆 + 多体模拟社会的 MVP：用户通过多轮「访谈式对话」让系统逐步构建自己的「复制人」
人格档案（traits / values / facts / style_samples），之后可与复制人聊天；
多个复制人还能进入一个共享的「模拟世界」，按 tick 自由生活：规划行动 → 相遇 →
双人对话 → 记忆回写 → 偶发的人格档案版本更新（显式演进，留存 diff 原因）。

## 架构

```
replicant/
├── replicant/
│   ├── main.py             # FastAPI 入口，挂载路由与静态单页
│   ├── config.py           # 环境变量配置
│   ├── db.py               # SQLModel 表定义与引擎工具
│   ├── llm.py              # LLM 协议 + OpenAI 兼容实现 + MockLLM（确定性，无网可用）
│   ├── interview/          # 访谈：确定性状态机（protocol.py）+ 多轮引擎（engine.py）
│   ├── persona/            # 人格档案（版本化）+ 记忆流（三因子加权检索 + 反思）
│   ├── chat.py             # 与复制人对话：profile + top-K 记忆组装 prompt
│   ├── simulation/         # 模拟社会：tick 世界循环 / 行动规划 / 双人对话
│   └── api/                # REST 路由
├── web/                    # 静态单页前端（vanilla JS，无构建链）
└── tests/                  # pytest，全部走 MockLLM，不依赖网络
```

关键设计：

- **访谈是确定性状态机**：自我介绍 → 人生故事 → 价值观 → 日常习惯 → 语言风格采样。
  每阶段有 min/max 轮数判据（回答太短视为敷衍），LLM 只负责生成下一个问题和
  从回答中抽取结构化事实，不参与推进决策。
- **记忆流**借鉴斯坦福 Generative Agents：`score = 0.3·recency + 0.4·importance + 0.3·relevance`。
  importance 由 LLM 打 1-10 分；recency 用自增 id 表示时间序并指数衰减；
  relevance 用词元重合度。
- **人格演进显式版本化**：聊天/对话绝不静默改 profile —— 只写入记忆；记忆积累达阈值触发
  反思（reflection），反思才可申请 profile patch，存为新版本 + diff 原因。

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `REPLICANT_LLM_BASE_URL` | OpenAI 兼容接口地址（LiteLLM / Ollama 等） | 空 → MockLLM |
| `REPLICANT_LLM_API_KEY` | API Key | 空 |
| `REPLICANT_LLM_MODEL` | 模型名 | 空 → MockLLM |
| `REPLICANT_LLM_MOCK` | `1` 强制使用 MockLLM | 关 |
| `REPLICANT_DB_URL` | SQLAlchemy 连接串 | `sqlite:///replicant.db` |

未配置齐 LLM 三要素时自动回退到 **MockLLM**（确定性台词与分数），可在无 LLM 的
环境下演示全链路。

## 运行

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows Git Bash
# 或 Linux/macOS: source .venv/bin/activate && pip install -r requirements.txt

# 测试
.venv/Scripts/python -m pytest -q

# 起服务（MockLLM 演示）
REPLICANT_LLM_MOCK=1 .venv/Scripts/python -m uvicorn replicant.main:app --port 8000
```

浏览器打开 <http://127.0.0.1:8000>：克隆列表 / 访谈 / 聊天 / 模拟世界四个视图。

## curl 示例

```bash
# 1. 创建访谈（返回第一轮提问）
curl -s -X POST localhost:8000/interviews -H 'Content-Type: application/json' \
  -d '{"owner_name":"张三"}'

# 2. 多轮回复推进（最短路径约 8 轮直到 status=done，拿到 clone_id）
curl -s -X POST localhost:8000/interviews/1/reply -H 'Content-Type: application/json' \
  -d '{"text":"我叫张三，是个开朗乐观的程序员。"}'

# 3. 与复制人聊天
curl -s -X POST localhost:8000/clones/1/chat -H 'Content-Type: application/json' \
  -d '{"message":"最近心情不太好怎么办？"}'

# 4. 调试入口：越过访谈直接建第二个复制人（常规路径仍是访谈）
curl -s -X POST localhost:8000/clones/quick -H 'Content-Type: application/json' \
  -d '{"name":"阿芳","traits":["随和"],"values":["朋友","健康"]}'

# 5. 模拟世界 tick + 时间线
curl -s -X POST localhost:8000/sim/tick
curl -s localhost:8000/sim/timeline

# 6. 人格演进版本史（含 diff 原因）
curl -s localhost:8000/clones/1/profile-history
```
