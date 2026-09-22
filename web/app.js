// 复制人 Replicant 前端（vanilla JS，无构建链）
// 流式：fetch + ReadableStream 解析 SSE（EventSource 不支持 POST，不用）

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp.json();
}
const post = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

// 按字节流读 SSE，TextDecoder 流式解码保证中文不被切碎
async function ssePost(url, body, handlers) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!resp.ok) {
    handlers.error && handlers.error(`HTTP ${resp.status}`);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message", data = null;
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) {
          try { data = JSON.parse(line.slice(5).trim()); } catch { data = line.slice(5).trim(); }
        }
      }
      if (data !== null && handlers[event]) handlers[event](data);
    }
  }
}

// ---------- 视图切换 ----------
const showView = (name) => {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $(`#view-${name}`).classList.add("active");
  if (name === "clones") loadClones();
  if (name === "chat") loadCloneOptions();
  if (name === "world") loadTimeline();
};
document.querySelectorAll(".nav-item").forEach((btn) => btn.addEventListener("click", () => showView(btn.dataset.view)));
document.querySelectorAll(".entry-card").forEach((btn) => btn.addEventListener("click", () => showView(btn.dataset.go)));

// ---------- 头像 / 气泡 ----------
const HUES = [28, 140, 200, 260, 330, 12, 90, 170];
function avatarHTML(name, size = 36) {
  const ch = (name || "？").trim()[0] || "？";
  let hash = 0;
  for (const c of name || "") hash = (hash * 31 + c.codePointAt(0)) >>> 0;
  const hue = HUES[hash % HUES.length];
  return `<div class="avatar" style="width:${size}px;height:${size}px;background:hsl(${hue},55%,62%)">${esc(ch)}</div>`;
}

function removeEmptyHint(log) {
  const hint = log.querySelector(".empty-hint");
  if (hint) hint.remove();
}

function appendBubble(logEl, role, text, name) {
  removeEmptyHint(logEl);
  const row = document.createElement("div");
  row.className = `msg-row ${role === "user" ? "me" : ""}`;
  row.innerHTML = `${avatarHTML(name)}<div class="msg-col"><div class="bubble-status"></div><div class="bubble">${esc(text)}</div></div>`;
  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;
  return row;
}

// 流式对方气泡：状态栏 + 可选思考折叠区 + 正文
function appendStreamingBubble(logEl, name) {
  removeEmptyHint(logEl);
  const row = document.createElement("div");
  row.className = "msg-row";
  row.innerHTML = `${avatarHTML(name)}<div class="msg-col">
    <div class="bubble-status">对方正在输入…</div>
    <details class="reasoning" hidden><summary>思考过程</summary><div class="reasoning-body"></div></details>
    <div class="bubble typing"></div></div>`;
  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;
  return {
    statusEl: row.querySelector(".bubble-status"),
    reasoning: row.querySelector("details.reasoning"),
    reasoningBody: row.querySelector(".reasoning-body"),
    bubble: row.querySelector(".bubble"),
    scroll: () => (logEl.scrollTop = logEl.scrollHeight),
  };
}

// ---------- 克隆列表 ----------
async function loadClones() {
  const grid = $("#clone-grid");
  grid.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
  const clones = await api("/clones");
  if (!clones.length) {
    grid.innerHTML = '<div class="empty-hint">这里还空着。造第一个复制人吧——访谈、闲聊、传段聊天记录都行。</div>';
    return;
  }
  grid.innerHTML = "";
  for (const c of clones) {
    const card = document.createElement("div");
    card.className = "clone-card";
    const summary = (c.traits || []).slice(0, 4).join("、") || "人格还在生长中";
    card.innerHTML = `
      <div class="clone-card-row">${avatarHTML(c.name)}<span class="clone-name">${esc(c.name)}</span>
      <span class="badge">profile v${c.profile_version ?? "?"}</span></div>
      <div class="clone-summary">${esc(summary)}</div>`;
    card.addEventListener("click", () => showCloneDetail(c.id, c.name));
    grid.appendChild(card);
  }
}

async function showCloneDetail(id, name) {
  const box = $("#clone-detail");
  box.innerHTML = '<div class="skeleton"></div>';
  const items = await api(`/clones/${id}/timeline`);
  const html = items
    .slice()
    .reverse()
    .map((it) => {
      const isVer = it.type === "profile_version";
      const m = isVer ? it.title.match(/v(\d+)/) : null;
      const title = isVer && m ? `<span class="ver">v${m[1]}</span>人格档案` : esc(it.title);
      const traits = it.traits && it.traits.length ? `<div class="tl-traits">特质：${esc(it.traits.join("、"))}</div>` : "";
      return `<div class="tl-card ${it.type}"><div class="tl-head"><span class="tl-title">${title}</span><span class="tl-src">${esc(it.source)}</span></div>
        <div class="tl-detail">${esc(it.detail)}</div>${traits}</div>`;
    })
    .join("");
  box.innerHTML = `<div class="view-head" style="margin-top:26px"><h1 style="font-size:18px">${esc(name)} 的演进时间线</h1></div>
    <div class="timeline">${html || '<div class="empty-hint">还没有故事，去聊聊就有了。</div>'}</div>`;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- 访谈 ----------
let interviewId = null;
let interviewName = "我";
const ivSend = $("#iv-send");

$("#iv-start").addEventListener("click", async () => {
  interviewName = $("#iv-name").value.trim() || "匿名";
  const data = await post("/interviews", { owner_name: interviewName });
  interviewId = data.interview_id;
  $("#iv-log").innerHTML = "";
  $("#iv-stage").textContent = `当前阶段：${data.stage}`;
  appendBubble($("#iv-log"), "agent", data.question, "访谈员");
});

async function sendInterviewReply() {
  const text = $("#iv-input").value.trim();
  if (!text || !interviewId) return;
  appendBubble($("#iv-log"), "user", text, interviewName);
  $("#iv-input").value = "";
  ivSend.disabled = true;
  const view = appendStreamingBubble($("#iv-log"), "访谈员");
  await ssePost(`/interviews/${interviewId}/reply/stream`, { text }, {
    status: (s) => { view.statusEl.textContent = s; view.scroll(); },
    reasoning: (r) => { view.reasoning.hidden = false; view.reasoningBody.textContent += r; },
    delta: (d) => { view.bubble.classList.remove("typing"); view.bubble.textContent += d; view.statusEl.textContent = ""; view.scroll(); },
    done: (data) => {
      view.bubble.classList.remove("typing");
      view.reasoning.hidden = true;
      if (data.status === "done") {
        view.statusEl.textContent = "";
        appendBubble($("#iv-log"), "agent", `访谈聊完了，${interviewName} 的复制人 #${data.clone_id} 已经立起来了。`, "访谈员");
        $("#iv-stage").textContent = "访谈已完成";
        interviewId = null;
      } else {
        $("#iv-stage").textContent = `当前阶段：${data.stage}`;
        view.statusEl.textContent = "";
      }
    },
    error: (e) => { view.statusEl.textContent = `出错了：${e}`; view.bubble.classList.remove("typing"); },
  });
  ivSend.disabled = false;
  $("#iv-input").focus();
}
ivSend.addEventListener("click", sendInterviewReply);
$("#iv-input").addEventListener("keydown", (e) => e.key === "Enter" && sendInterviewReply());

// ---------- 即时聊天会话 ----------
let chatSessionId = null;
let sessionName = "我";
const csSend = $("#cs-send");

$("#cs-start").addEventListener("click", async () => {
  sessionName = $("#cs-name").value.trim() || "匿名";
  const data = await post("/chat-sessions", { name: sessionName });
  chatSessionId = data.session_id;
  $("#cs-log").innerHTML = "";
  $("#cs-hint").textContent = "聊到差不多 3 条就能定型。";
  appendBubble($("#cs-log"), "agent", data.greeting, "系统");
});

$("#cs-finalize").addEventListener("click", async () => {
  if (!chatSessionId) return;
  const data = await post(`/chat-sessions/${chatSessionId}/finalize`);
  appendBubble($("#cs-log"), "agent", `好，${sessionName} 的复制人 #${data.clone_id} 成型了。想继续聊也行，它会接着长。`, "系统");
  $("#cs-hint").textContent = `克隆 #${data.clone_id} 已定型`;
  $("#cs-finalize").disabled = true;
});

async function sendSessionMsg() {
  const text = $("#cs-input").value.trim();
  if (!text || !chatSessionId) return;
  appendBubble($("#cs-log"), "user", text, sessionName);
  $("#cs-input").value = "";
  csSend.disabled = true;
  const view = appendStreamingBubble($("#cs-log"), "系统");
  await ssePost(`/chat-sessions/${chatSessionId}/msg/stream`, { text }, {
    status: (s) => { view.statusEl.textContent = s; view.scroll(); },
    reasoning: (r) => { view.reasoning.hidden = false; view.reasoningBody.textContent += r; },
    delta: (d) => { view.bubble.classList.remove("typing"); view.bubble.textContent += d; view.statusEl.textContent = ""; view.scroll(); },
    done: (data) => {
      view.bubble.classList.remove("typing");
      view.reasoning.hidden = true;
      view.statusEl.textContent = "";
      if (data.status === "finalized") {
        $("#cs-hint").textContent = `克隆 #${data.clone_id} 已定型（profile v${data.profile_version ?? 1}），继续聊它会继续变。`;
        $("#cs-finalize").disabled = true;
      } else {
        $("#cs-hint").textContent = `聊了 ${data.msg_count} 条，记下 ${data.draft_facts} 条事实` + (data.ready ? "，可以定型了" : "");
        $("#cs-finalize").disabled = !data.ready;
      }
    },
    error: (e) => { view.statusEl.textContent = `出错了：${e}`; view.bubble.classList.remove("typing"); },
  });
  csSend.disabled = false;
  $("#cs-input").focus();
}
csSend.addEventListener("click", sendSessionMsg);
$("#cs-input").addEventListener("keydown", (e) => e.key === "Enter" && sendSessionMsg());

// ---------- 上传聊天记录 ----------
$("#up-submit").addEventListener("click", async () => {
  const alias = $("#up-alias").value.trim();
  const text = $("#up-text").value.trim();
  const box = $("#up-result");
  if (!alias || !text) { box.textContent = "先填昵称，再把记录贴进来。"; return; }
  box.textContent = "正在读这些记录……";
  try {
    const data = await post("/clones/upload", { alias, text, owner_name: $("#up-name").value.trim() || null });
    box.textContent =
      `克隆 #${data.clone_id}「${data.name}」立起来了。本人消息 ${data.owner_messages} 条，写进记忆 ${data.memories_written} 条，` +
      `当场反思了 ${data.reflections} 回，人格已经长到 v${data.profile_version}。\n\n` +
      `特质：${data.traits.join("、") || "（还有待聊出来）"}\n价值观：${data.values.join("、") || "（还有待聊出来）"}`;
  } catch (e) {
    box.textContent = `没成：${e.message.includes("422") ? "记录里没找到这个昵称说的话，核对一下？" : e.message}`;
  }
});

// ---------- 与复制人聊天 ----------
let chatName = "复制人";
const chatSendBtn = $("#chat-send");

async function loadCloneOptions() {
  const clones = await api("/clones");
  $("#chat-clone").innerHTML = clones.map((c) => `<option value="${c.id}" data-name="${esc(c.name)}">#${c.id} ${esc(c.name)}</option>`).join("");
  updateChatTarget();
}
function updateChatTarget() {
  const opt = $("#chat-clone").selectedOptions[0];
  chatName = opt ? opt.dataset.name : "复制人";
  $("#chat-target").textContent = opt ? `正在和 #${opt.value} ${chatName} 聊` : "还没有复制人，先去造一个";
}
$("#chat-clone").addEventListener("change", updateChatTarget);

async function sendChat() {
  const message = $("#chat-input").value.trim();
  const cloneId = $("#chat-clone").value;
  if (!message || !cloneId) return;
  appendBubble($("#chat-log"), "user", message, "我");
  $("#chat-input").value = "";
  chatSendBtn.disabled = true;
  const view = appendStreamingBubble($("#chat-log"), chatName);
  await ssePost(`/clones/${cloneId}/chat/stream`, { message }, {
    status: (s) => { view.statusEl.textContent = s; view.scroll(); },
    reasoning: (r) => { view.reasoning.hidden = false; view.reasoningBody.textContent += r; },
    delta: (d) => { view.bubble.classList.remove("typing"); view.bubble.textContent += d; view.statusEl.textContent = ""; view.scroll(); },
    done: (data) => {
      view.bubble.classList.remove("typing");
      view.reasoning.hidden = true;
      view.statusEl.textContent = `profile v${data.profile_version}`;
      $("#chat-target").textContent = `正在和 #${cloneId} ${chatName} 聊 · profile v${data.profile_version}`;
    },
    error: (e) => { view.statusEl.textContent = `出错了：${e}`; view.bubble.classList.remove("typing"); },
  });
  chatSendBtn.disabled = false;
  $("#chat-input").focus();
}
chatSendBtn.addEventListener("click", sendChat);
$("#chat-input").addEventListener("keydown", (e) => e.key === "Enter" && sendChat());

// ---------- 模拟世界 ----------
async function loadTimeline() {
  const [state, events] = await Promise.all([api("/sim/state"), api("/sim/timeline")]);
  $("#sim-state").textContent = `现在是第 ${state.tick} 格`;
  $("#timeline").innerHTML = events.length
    ? events
        .map((e) => `<div class="tl-card sim_event"><div class="tl-head"><span class="tl-title">tick ${e.tick}</span><span class="tl-src">${esc(e.kind)}</span></div><div class="tl-detail">${esc(e.description)}</div></div>`)
        .reverse()
        .join("")
    : '<div class="empty-hint">世界还没开始转。拨快一格时间试试。</div>';
}

const tickBtn = $("#sim-tick");
tickBtn.addEventListener("click", async () => {
  tickBtn.disabled = true;
  tickBtn.textContent = "时间在走…";
  await post("/sim/tick");
  tickBtn.disabled = false;
  tickBtn.textContent = "拨快一格时间";
  loadTimeline();
});

loadClones();
