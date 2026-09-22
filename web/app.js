// 复制人 Replicant 单页前端（vanilla JS，无构建链）
const api = async (path, options) => {
  const resp = await fetch(path, options);
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp.json();
};
const post = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

const $ = (sel) => document.querySelector(sel);

// ---------- 视图切换 ----------
const showView = (name) => {
  document.querySelectorAll("nav .tab").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $(`#view-${name}`).classList.add("active");
  if (name === "clones") loadClones();
  if (name === "chat") loadCloneOptions();
  if (name === "world") loadTimeline();
};
window.goView = showView; // 供克隆列表页的内联按钮调用
document.querySelectorAll("nav .tab").forEach((btn) =>
  btn.addEventListener("click", () => showView(btn.dataset.view))
);

// ---------- 克隆列表 ----------
async function loadClones() {
  const clones = await api("/clones");
  $("#clone-list").innerHTML = clones.length
    ? clones.map((c) => `<div class="card" data-id="${c.id}">#${c.id} ${c.name}（profile v${c.profile_version}）</div>`).join("")
    : "<p>还没有复制人，去访谈或快速建档吧。</p>";
  document.querySelectorAll("#clone-list .card").forEach((card) =>
    card.addEventListener("click", () => showCloneDetail(card.dataset.id))
  );
}

async function showCloneDetail(id) {
  // 演进时间线：profile 版本 + 重要记忆 + 模拟事件，展示无限迭代过程
  const items = await api(`/clones/${id}/timeline`);
  $("#clone-detail").innerHTML =
    `<h3>#${id} 演进时间线</h3>` +
    items
      .map((it) => {
        const badge = {
          profile_version: "📌 " + it.title,
          memory: "🧠 " + it.title,
          sim_event: "🌍 " + it.title,
        }[it.type] || it.title;
        const extra = it.traits ? `<br>traits: ${it.traits.join(", ")}` : "";
        return `<div class="event"><div class="meta">${badge}　来源：${it.source}</div>${it.detail}${extra}</div>`;
      })
      .reverse()
      .join("");
}

$("#quick-create").addEventListener("click", async () => {
  const split = (s) => s.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
  await post("/clones/quick", {
    name: $("#quick-name").value || "调试克隆",
    traits: split($("#quick-traits").value),
    values: split($("#quick-values").value),
  });
  loadClones();
});

// ---------- 访谈 ----------
let interviewId = null;
const appendMsg = (log, role, text) => {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = (role === "user" ? "我：" : "访谈员：") + text;
  $(log).appendChild(div);
  $(log).scrollTop = $(log).scrollHeight;
};

$("#iv-start").addEventListener("click", async () => {
  const name = $("#iv-name").value || "匿名";
  const data = await post("/interviews", { owner_name: name });
  interviewId = data.interview_id;
  $("#iv-log").innerHTML = "";
  $("#iv-stage").textContent = `当前阶段：${data.stage}`;
  appendMsg("#iv-log", "agent", data.question);
});

async function sendInterviewReply() {
  const text = $("#iv-input").value.trim();
  if (!text || !interviewId) return;
  appendMsg("#iv-log", "user", text);
  $("#iv-input").value = "";
  const data = await post(`/interviews/${interviewId}/reply`, { text });
  if (data.status === "done") {
    appendMsg("#iv-log", "agent", `访谈结束，你的复制人 #${data.clone_id} 诞生了！`);
    $("#iv-stage").textContent = "访谈已完成";
    interviewId = null;
  } else {
    $("#iv-stage").textContent = `当前阶段：${data.stage}`;
    appendMsg("#iv-log", "agent", data.question);
  }
}
$("#iv-send").addEventListener("click", sendInterviewReply);
$("#iv-input").addEventListener("keydown", (e) => e.key === "Enter" && sendInterviewReply());

// ---------- 即时聊天会话 ----------
let chatSessionId = null;

$("#cs-start").addEventListener("click", async () => {
  const name = $("#cs-name").value || "匿名";
  const data = await post("/chat-sessions", { owner_name: name });
  chatSessionId = data.session_id;
  $("#cs-log").innerHTML = "";
  $("#cs-hint").textContent = "聊到差不多 3 条就可以定型，当然也可以一直聊。";
  appendMsg("#cs-log", "agent", data.greeting);
});

async function sendSessionMsg() {
  const text = $("#cs-input").value.trim();
  if (!text || !chatSessionId) return;
  appendMsg("#cs-log", "user", text);
  $("#cs-input").value = "";
  const data = await post(`/chat-sessions/${chatSessionId}/msg`, { text });
  appendMsg("#cs-log", "agent", data.reply);
  if (data.status === "finalized") {
    $("#cs-hint").textContent = `克隆 #${data.clone_id} 已定型（profile v${data.profile_version || 1}），继续聊天会持续演进。`;
    $("#cs-finalize").disabled = true;
  } else {
    $("#cs-hint").textContent = `已聊 ${data.msg_count} 条，抽取到 ${data.draft_facts} 条事实` + (data.ready ? "，可以定型了！" : "");
    $("#cs-finalize").disabled = !data.ready;
  }
}
$("#cs-send").addEventListener("click", sendSessionMsg);
$("#cs-input").addEventListener("keydown", (e) => e.key === "Enter" && sendSessionMsg());

$("#cs-finalize").addEventListener("click", async () => {
  if (!chatSessionId) return;
  const data = await post(`/chat-sessions/${chatSessionId}/finalize`);
  appendMsg("#cs-log", "agent", `定型完成：你的复制人 #${data.clone_id} 诞生了！之后继续聊天、上传记录或进模拟社会都会让它持续演进。`);
  $("#cs-hint").textContent = `克隆 #${data.clone_id} 已定型。`;
  $("#cs-finalize").disabled = true;
});

// ---------- 上传聊天记录 ----------
$("#up-submit").addEventListener("click", async () => {
  const alias = $("#up-alias").value.trim();
  const text = $("#up-text").value.trim();
  if (!alias || !text) {
    $("#up-result").textContent = "请填写本人昵称并粘贴聊天记录。";
    return;
  }
  try {
    const data = await post("/clones/upload", {
      alias,
      text,
      owner_name: $("#up-name").value.trim() || null,
    });
    $("#up-result").textContent =
      `克隆 #${data.clone_id}「${data.name}」已生成！本人消息 ${data.owner_messages} 条，写入记忆 ${data.memories_written} 条，` +
      `触发反思 ${data.reflections} 次，当前 profile v${data.profile_version}。\n` +
      `traits: ${data.traits.join(", ")}\nvalues: ${data.values.join(", ")}`;
  } catch (e) {
    $("#up-result").textContent = `出错：${e.message}`;
  }
});

// ---------- 与复制人聊天 ----------
async function loadCloneOptions() {
  const clones = await api("/clones");
  $("#chat-clone").innerHTML = clones.map((c) => `<option value="${c.id}">#${c.id} ${c.name}</option>`).join("");
}

async function sendChat() {
  const message = $("#chat-input").value.trim();
  const cloneId = $("#chat-clone").value;
  if (!message || !cloneId) return;
  appendMsg("#chat-log", "user", message);
  $("#chat-input").value = "";
  const data = await post(`/clones/${cloneId}/chat`, { message });
  appendMsg("#chat-log", "agent", data.reply);
  $("#chat-profile-ver").textContent = `profile v${data.profile_version}`;
}
$("#chat-send").addEventListener("click", sendChat);
$("#chat-input").addEventListener("keydown", (e) => e.key === "Enter" && sendChat());

// ---------- 模拟世界 ----------
async function loadTimeline() {
  const [state, events] = await Promise.all([api("/sim/state"), api("/sim/timeline")]);
  $("#sim-state").textContent = `当前 tick：${state.tick}`;
  $("#timeline").innerHTML = events
    .map((e) => `<div class="event"><div class="meta">tick ${e.tick} · ${e.kind}</div>${e.description}</div>`)
    .reverse()
    .join("");
}

$("#sim-tick").addEventListener("click", async () => {
  await post("/sim/tick");
  loadTimeline();
});

loadClones();
