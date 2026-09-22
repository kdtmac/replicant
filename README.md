# 复制人 Replicant

人格克隆 + 多体模拟社会的 MVP：用户让系统逐步构建自己的「复制人」人格档案
（traits / values / facts / style_samples），之后可与复制人聊天；
多个复制人还能进入一个共享的「模拟世界」，按 tick 自由生活：规划行动 → 相遇 →
双人对话 → 记忆回写 → 偶发的人格档案版本更新（显式演进，留存 diff 原因）。

## 三种创建方式

1. **访谈式（分阶段状态机）**：自我介绍 → 人生故事 → 价值观 → 日常习惯 → 语言风格采样。
   每阶段有 min/max 轮数判据（回答太短视为敷衍），LLM 只负责生成下一个问题和
   从回答中抽取结构化事实，不参与推进决策。
2. **即时聊天模式**：不做进度条式访谈，自由聊天。每轮对话后台持续抽取
   facts / traits / values / style_samples 累积成草稿 profile；消息数达到轻量阈值
   （默认 3 条）后即可随时定型（也支持 `REPLICANT_AUTO_FINALIZE_MSGS` 自动定型）。
   定型后继续聊天 = 与克隆说话，记忆继续长、版本继续堆。
3. **上传聊天记录快速生成**：粘贴一段聊天导出文本并指定本人昵称。解析器宽容地支持
   `[时间] 昵称: 内容`、`昵称 时间` 换行（可多行内容）、纯 `昵称: 内容` 三种格式；
   只取本人消息做批量抽取、用本人原句做风格样本，**立即**生成 profile v1 和克隆。

另有调试入口 `POST /clones/quick` 直接建档（常规演示请走上面三种方式）。

## 无限持续迭代（不设上限）

克隆建成后人格演进永不封顶：

- 持续聊天、定型后的会话消息、模拟社会经历、再次上传的聊天记录，全部写入记忆流；
- 记忆积累达到阈值触发 reflection：汇聚高层认知并可申请 profile patch，
  产生 v1 → v2 → v3 … 的新版本（每次都有 diff 原因与来源标注）；
- 反思计数按阈值减量而非清零，因此批量注入（记忆数量是阈值的数倍）会连续触发多次
  反思与 patch；
- `GET /clones/{id}/timeline` 把 profile 版本、重要记忆、模拟事件汇成一条演进时间线，
  前端克隆详情页即此「无限迭代」视图。

## 架构

```
replicant/
├── replicant/
│   ├── main.py             # FastAPI 入口，挂载路由与静态单页
│   ├── config.py           # 环境变量配置
│   ├── db.py               # SQLModel 表定义与引擎工具
│   ├── llm.py              # LLM 协议 + OpenAI 兼容实现 + MockLLM（确定性，无网可用）
│   ├── interview/          # 创建方式一：访谈状态机（protocol.py）+ 多轮引擎（engine.py）
│   ├── chatsession.py      # 创建方式二：即时聊天会话（草稿累积 + finalize）
│   ├── chatlog_parser.py   # 聊天记录解析器（三种格式，宽容容错）
│   ├── upload.py           # 创建方式三：上传记录一次性建档
│   ├── persona/            # 人格档案（版本化 + source 标注）+ 记忆流（检索 + 反思 + 批量吸收）
│   ├── chat.py             # 与复制人对话：profile + top-K 记忆组装 prompt
│   ├── timeline.py         # 演进时间线（profile 版本 + 重要记忆 + 模拟事件）
│   ├── simulation/         # 模拟社会：tick 世界循环 / 行动规划 / 双人对话
│   └── api/                # REST 路由（interview / clone / session / sim）
├── web/                    # 静态单页前端（vanilla JS，无构建链）
└── tests/                  # pytest，全部走 MockLLM，不依赖网络
```

关键设计：

- **记忆流**借鉴斯坦福 Generative Agents：`score = 0.3·recency + 0.4·importance + 0.3·relevance`。
  importance 由 LLM 打 1-10 分；recency 用自增 id 表示时间序并指数衰减；
  relevance 用词元重合度。
- **人格演进显式版本化**：聊天/对话绝不静默改 profile —— 只写入记忆；反思才可申请
  profile patch，存为新版本 + 来源（interview/chat_session/upload/quick/reflection）+ diff 原因。

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `REPLICANT_LLM_BASE_URL` | OpenAI 兼容接口地址（LiteLLM / Ollama 等） | 空 → MockLLM |
| `REPLICANT_LLM_API_KEY` | API Key | 空 |
| `REPLICANT_LLM_MODEL` | 模型名 | 空 → MockLLM |
| `REPLICANT_LLM_MOCK` | `1` 强制使用 MockLLM | 关 |
| `REPLICANT_DB_URL` | SQLAlchemy 连接串 | `sqlite:///replicant.db` |
| `REPLICANT_AUTO_FINALIZE_MSGS` | 即时聊天自动定型阈值（消息数，`0`=关闭） | `0` |

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

浏览器打开 <http://127.0.0.1:8000>：克隆列表 / 访谈 / 即时聊天 / 上传记录 /
与复制人聊天 / 模拟世界六个视图。

## API 一览与 curl 示例

### 创建方式一：访谈

```bash
curl -s -X POST localhost:8000/interviews -H 'Content-Type: application/json' \
  -d '{"owner_name":"张三"}'
# → {interview_id, question, stage}

curl -s -X POST localhost:8000/interviews/1/reply -H 'Content-Type: application/json' \
  -d '{"text":"我叫张三，是个开朗乐观的程序员。"}'
# → 多轮推进（最短约 8 轮）直到 {"status":"done","clone_id":1}
```

### 创建方式二：即时聊天

```bash
curl -s -X POST localhost:8000/chat-sessions -H 'Content-Type: application/json' \
  -d '{"owner_name":"王五"}'
# → {session_id, greeting}

curl -s -X POST localhost:8000/chat-sessions/1/msg -H 'Content-Type: application/json' \
  -d '{"text":"我是个开朗的人，平时喜欢早起跑步。"}'
# → {reply, msg_count, ready, draft_facts}；ready=true 后可随时定型

curl -s -X POST localhost:8000/chat-sessions/1/finalize
# → {"status":"finalized","clone_id":1,"profile_version":1}（幂等）
# 定型后继续 /msg 即与克隆聊天迭代
```

### 创建方式三：上传聊天记录

```bash
curl -s -X POST localhost:8000/clones/upload -H 'Content-Type: application/json' \
  -d '{"alias":"阿明","text":"[2024-03-01 09:13] 阿明: 我一般十一点睡七点起，雷打不动\n阿芳: 你真自律\n阿明: 家庭最重要，钱够花就行"}'
# → {clone_id, owner_messages, traits, values, style_samples, memories_written,
#    reflections, profile_version}；批量记忆注入会当场触发多次反思堆版本
```

### 迭代与观察

```bash
curl -s -X POST localhost:8000/clones/1/chat -H 'Content-Type: application/json' \
  -d '{"message":"最近心情不太好怎么办？"}'   # 与克隆聊天（只写记忆不改 profile）

curl -s -X POST localhost:8000/clones/quick -H 'Content-Type: application/json' \
  -d '{"name":"阿芳","traits":["随和"],"values":["朋友","健康"]}'   # 调试入口

curl -s -X POST localhost:8000/sim/tick        # 模拟世界
curl -s localhost:8000/sim/timeline            # 世界事件流
curl -s localhost:8000/clones/1/profile-history  # 人格版本史（含来源 + diff 原因）
curl -s localhost:8000/clones/1/timeline       # 演进时间线（版本 + 重要记忆 + 模拟事件）
```

## 已知限制

- MockLLM 台词为模板套路，仅演示通路；真实表达力需配置 OpenAI 兼容接口。
- 记忆 relevance 用词元重合（无 embedding）；解析器对极端非标格式会退化为续行合并。
- 表结构变更不做迁移：旧版 `replicant.db` 与本版不兼容，删除后重建即可。
- 无鉴权、无多用户隔离。
