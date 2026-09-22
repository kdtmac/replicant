# 真实 LLM 全链路调试脚本：驱动 5 步流程并把代表性输出增量记录到 docs/debug-transcript.md
# 运行：.venv/Scripts/python scripts_debug_real.py
import httpx

BASE = "http://127.0.0.1:8770"

f = open("docs/debug-transcript.md", "w", encoding="utf-8")
f.write("# 真实 LLM 调试 Transcript\n\n")
f.write("- 模型：`m-20260824185732-n8z5w/kimi-k3`（Kimi K3，thinking 模型，取 `content`）\n")
f.write("- base_url：`https://your-openai-compatible-endpoint/v1`\n- 调试日期：2026-09-22\n")


def rec(title: str, body: str) -> None:
    f.write(f"\n## {title}\n\n```\n{body}\n```\n")
    f.flush()
    print(f"[{title}] done")


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=180.0)

    # 1. 结构化访谈：扮演普通用户，答到收敛为止
    r = c.post("/interviews", json={"owner_name": "阿磊"}).json()
    iv_id = r["interview_id"]
    log = [f"访谈员：{r['question']}"]
    answers = [
        "我叫阿磊，大家都说我是个挺开朗的人，朋友多",
        "我在成都长大，大学毕业一个人跑去了深圳，那算是个大转折吧",
        "最影响我的应该是我爸，他做什么事都特别认真，我大概遗传了他这点",
        "我最看重家庭，赚钱够花就行，别为了钱把生活弄丢了",
        "一般八点起，晚上有空就去江边跑步，周末钓鱼",
        "别慌，天塌不下来，慢慢来",
        "这鬼天气一出门就一身汗，受够了",
        "再想想……好像该说的都说了",
    ]
    clone1 = None
    for i, ans in enumerate(answers):
        log.append(f"我：{ans}")
        r = c.post(f"/interviews/{iv_id}/reply", json={"text": ans}).json()
        if r.get("status") == "done":
            clone1 = r["clone_id"]
            log.append(f"→ 访谈结束，clone_id={clone1}（共 {i+1} 轮回答）")
            break
        log.append(f"[stage={r['stage']}]\n访谈员：{r['question']}")
    rec("1. 结构化访谈（真实模型，答到收敛）", "\n\n".join(log))
    if clone1 is not None:
        hist = c.get(f"/clones/{clone1}/profile-history")
        v1 = hist.json()[0]
        rec("1b. 访谈产出的 profile v1",
            f"version={v1['version']} source={v1['source']}\n"
            f"traits={v1['traits']}\nvalues={v1['values']}\n"
            f"facts=\n" + "\n".join("- " + x for x in v1["facts"][:8]) +
            f"\nstyle_samples={v1['style_samples'][:3]}")
    else:
        rec("1b. 访谈未收敛", f"最后一次返回：{r}")

    # 2. 即时聊天会话 → finalize → 继续聊
    r = c.post("/chat-sessions", json={"owner_name": "小梦"}).json()
    sid = r["session_id"]
    log = [f"系统：{r['greeting']}"]
    for msg in ["我刚下班，累死了，今天开了四个会", "我一般下班就瘫在沙发上看剧，偶尔撸猫", "我这人吧，吃软不吃硬，别跟我抬杠就行"]:
        log.append(f"我：{msg}")
        r = c.post(f"/chat-sessions/{sid}/msg", json={"text": msg}).json()
        log.append(f"系统：{r['reply']}  （msg_count={r['msg_count']} ready={r['ready']} facts={r.get('draft_facts')}）")
    fin = c.post(f"/chat-sessions/{sid}/finalize").json()
    clone2 = fin.get("clone_id")
    log.append(f"→ finalize：clone_id={clone2}")
    r = c.post(f"/chat-sessions/{sid}/msg", json={"text": "你说我最近是不是该换个工作"}).json()
    log.append(f"我：你说我最近是不是该换个工作\n克隆：{r.get('reply')}")
    rec("2. 即时聊天会话 → finalize → 继续聊（真实模型）", "\n\n".join(log))

    # 3. 上传聊天记录（混合三种格式）
    wechat = (
        "[2024-03-01 09:12] 阿芳: 早啊，昨晚睡得好吗\n"
        "[2024-03-01 09:13] 老周: 还行，十一点睡七点起，雷打不动\n"
        "[2024-03-01 09:15] 老周: 哈哈大家都说我很自律，其实就是习惯了\n"
        "老周 2024-02-25 20:01\n工作再忙也得陪家里人，家庭最重要，这个是底线\n"
        "[2024-02-20 14:00] 老周: 钱够花就行，我最看重的还是健康\n"
        "老周: 周末去爬山不，我最近迷上徒步了\n"
        "[2024-02-18 11:31] 老周: 别慌，天塌不下来，慢慢来\n"
    )
    r = c.post("/clones/upload", json={"alias": "老周", "text": wechat})
    clone3 = None
    if r.status_code == 200:
        up = r.json()
        clone3 = up["clone_id"]
        rec("3. 上传聊天记录秒建（真实模型批量抽取，混合三种消息格式）",
            f"clone_id={clone3} owner_messages={up['owner_messages']}\n"
            f"traits={up['traits']}\nvalues={up['values']}\n"
            f"facts=\n" + "\n".join("- " + x for x in up["facts"][:8]) +
            f"\nstyle_samples=\n" + "\n".join("- " + x for x in up["style_samples"][:4]) +
            f"\nmemories_written={up['memories_written']} reflections={up['reflections']} → profile v{up['profile_version']}")
    else:
        rec("3. 上传聊天记录（失败！）", f"HTTP {r.status_code}: {r.text[:300]}")

    # 4. 与克隆聊天
    lines = []
    for msg in ["最近心情不太好怎么办", "给我推荐个放松的方式"]:
        r = c.post(f"/clones/{clone1}/chat", json={"message": msg}).json()
        lines.append(f"我：{msg}\n阿磊的复制人：{r.get('reply')}")
    rec("4. 与克隆聊天（真实模型，应短、口语、像人）", "\n\n".join(lines))

    # 5. 两次 sim tick
    ev_lines = []
    for _ in range(2):
        r = c.post("/sim/tick").json()
        for e in r.get("events", []):
            ev_lines.append(f"tick{e['tick']} [{e['kind']}]\n{e['description']}")
    rec("5. 模拟世界两次 tick（真实模型双克隆对话）", "\n\n".join(ev_lines))

    if clone1 is not None:
        tl = c.get(f"/clones/{clone1}/timeline").json()
        rec("6 附. 克隆演进时间线（阿磊）",
            "\n".join(f"[{i['type']}|{i['source']}] {i['title']} — {i['detail'][:80]}" for i in tl[:12]))

    f.close()


if __name__ == "__main__":
    main()
    print("ALL DONE")
