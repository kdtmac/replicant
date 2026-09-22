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
document.querySelectorAll("nav .tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav .tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    $(`#view-${btn.dataset.view}`).classList.add("active");
    if (btn.dataset.view === "clones") loadClones();
    if (btn.dataset.view === "chat") loadCloneOptions();
    if (btn.dataset.view === "world") loadTimeline();
  });
});

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
  const history = await api(`/clones/${id}/profile-history`);
  $("#clone-detail").innerHTML =
    `<h3>#${id} 人格演进史</h3>` +
    history
      .map(
        (v) =>
          `<pre>v${v.version}　${v.diff_reason || ""}\ntraits: ${v.traits.join(", ")}\nvalues: ${v.values.join(
            ", "
          )}\nfacts: ${v.facts.join("；")}\nstyle: ${v.style_samples.join("；")}</pre>`
      )
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
