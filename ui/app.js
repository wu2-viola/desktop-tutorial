"use strict";
/* 三栏 UI：左资源 / 中代码 / 右对话。工具调用一条条摊开 —— 必须看得见。 */

const $ = (id) => document.getElementById(id);
const stream = $("stream");
let running = false;
let evtSource = null;

/* ---------- 左栏：资源树 ---------- */
async function loadTree(path = "") {
  const res = await fetch(`/api/tree?path=${encodeURIComponent(path)}`);
  if (!res.ok) return;
  const data = await res.json();
  $("tree-path").textContent = "workspace/" + (path ? path + "/" : "");
  const ul = $("tree");
  ul.innerHTML = "";
  if (path) {
    const up = document.createElement("li");
    up.className = "dir";
    up.textContent = ".. (上级)";
    up.onclick = () => loadTree(path.split("/").slice(0, -1).join("/"));
    ul.appendChild(up);
  }
  for (const e of data.entries) {
    const li = document.createElement("li");
    li.className = e.type;
    li.textContent = e.name;
    li.title = e.path;
    li.onclick = () => e.type === "dir" ? loadTree(e.path) : openFile(e.path);
    ul.appendChild(li);
  }
}

/* ---------- 中栏：文件查看 ---------- */
async function openFile(path) {
  $("file-title").textContent = path;
  $("file-view").textContent = "加载中…";
  const res = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  if (!data.ok) {
    $("file-view").textContent = data.output || "读取失败";
    return;
  }
  let truncated = false;
  let text = data.output;
  const m = text.match(/……（还有 (\d+) 行/);
  if (m) { truncated = `（还有 ${m[1]} 行未显示）`; }
  $("file-view").textContent = text;
  if (truncated) $("file-view").textContent += `\n\n${truncated}`;
}

/* ---------- 右栏：对话与工具卡片 ---------- */
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
const scrollDown = () => { stream.scrollTop = stream.scrollHeight; };

function addToolCard(ev) {
  const isMcp = ev.tool.startsWith("mcp__");
  const card = el("div", `tool-card ${ev.ok ? "ok" : "fail"}`);
  const head = el("div", "tc-head");
  const name = el("span", "tc-name");
  if (isMcp) {
    name.appendChild(el("span", "mcp-tag", "MCP"));
    name.appendChild(document.createTextNode(ev.tool.replace(/^mcp__/, "").replace("__", " · ")));
  } else {
    name.textContent = ev.tool;
  }
  head.appendChild(name);
  head.appendChild(el("span", "tc-status", ev.ok ? "✓ 成功" : "✗ 失败"));
  card.appendChild(head);
  card.appendChild(el("div", "tc-meta", `${ev.error || ""} ${ev.elapsed_ms || 0}ms`));

  const pre = el("pre");
  const out = ev.output || "";
  if (ev.tool === "edit" || out.split("\n").some(l => /^[+-@]/.test(l))) {
    for (const line of out.split("\n")) {          // diff 绿加红减
      const span = el("span",
        line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" :
        line.startsWith("@@") ? "diff-hunk" : undefined, line + "\n");
      pre.appendChild(span);
    }
  } else {
    pre.textContent = out || "(无输出)";
  }
  card.appendChild(pre);
  stream.appendChild(card);
  scrollDown();
}

function setRunning(v) {
  running = v;
  $("btn-send").disabled = v;
  $("btn-stop").disabled = !v;
}

function runTask(task) {
  if (running || !task.trim()) return;
  setRunning(true);
  stream.appendChild(el("div", "msg user", task));
  const typing = el("div", "typing", "思考中…");
  stream.appendChild(typing);
  scrollDown();

  let current = null;                                // 当前正在流的 assistant 气泡
  evtSource = new EventSource(`/api/run/stream?task=${encodeURIComponent(task)}`);
  evtSource.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "__done__") { evtSource.close(); setRunning(false); typing.remove(); return; }
    if (ev.type === "provider") {
      $("provider-badge").textContent = ev.name === "deepseek" ? "模型 · DeepSeek" : "模型 · 离线 mock";
      $("provider-badge").classList.toggle("warn", ev.name !== "deepseek");
      if (ev.name !== "deepseek") typing.textContent = "未配置 Key，走离线 mock 演示…";
      return;
    }
    if (ev.type === "assistant_text") {
      typing.remove();
      if (!current) { current = el("div", "msg assistant"); stream.appendChild(current); }
      current.textContent += ev.delta;
      scrollDown();
      return;
    }
    current = null;
    if (ev.type === "tool_end") addToolCard(ev);
    else if (ev.type === "final") stream.appendChild(el("div", "final-line", "✓ 任务完成"));
    else if (ev.type === "stopped") stream.appendChild(el("div", "stopped-line", `■ 停止：${ev.reason}`));
    else if (ev.type === "error") { stream.appendChild(el("div", "error-line", ev.message)); }
    scrollDown();
  };
  evtSource.onerror = () => {
    typing.remove();
    if (running) stream.appendChild(el("div", "stopped-line", "连接结束"));
    evtSource.close();
    setRunning(false);
  };
}

/* ---------- 设置 ---------- */
async function openSettings() {
  const cfg = await (await fetch("/api/config")).json();
  $("cfg-key").value = "";
  $("cfg-key").placeholder = cfg.has_key ? `已保存（${cfg.key_hint}），留空则不修改` : "sk-...";
  $("cfg-url").value = cfg.base_url || "";
  $("cfg-model").value = cfg.model || "";
  $("settings-modal").classList.remove("hidden");
}

async function saveSettings() {
  const body = { base_url: $("cfg-url").value.trim(), model: $("cfg-model").value.trim() };
  const key = $("cfg-key").value.trim();
  if (key) body.api_key = key;
  await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  $("settings-modal").classList.add("hidden");
  refreshBadges();
}

async function refreshBadges() {
  const cfg = await (await fetch("/api/config")).json();
  $("provider-badge").textContent = cfg.has_key ? "模型 · 已配置" : "模型 · 未配置（走离线 mock）";
  $("provider-badge").classList.toggle("warn", !cfg.has_key);
  const ok = (cfg.mcp || []).filter(s => s.ok).length;
  const total = (cfg.mcp || []).length;
  const badge = $("mcp-badge");
  badge.textContent = total ? `MCP · ${ok}/${total} server 在线` : "MCP · 无配置";
  badge.className = "badge " + (ok ? "mcp-on" : "mcp-off");
  badge.title = (cfg.mcp || []).map(s => `${s.server}: ${s.ok ? "ok" : s.error}`).join("\n");
}

/* ---------- 绑定 ---------- */
$("btn-send").onclick = () => { runTask($("task-input").value); $("task-input").value = ""; };
$("task-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !running) { runTask($("task-input").value); $("task-input").value = ""; }
});
$("btn-stop").onclick = async () => { await fetch("/api/interrupt", { method: "POST" }); };
$("btn-settings").onclick = openSettings;
$("cfg-cancel").onclick = () => $("settings-modal").classList.add("hidden");
$("cfg-save").onclick = saveSettings;

loadTree();
refreshBadges();
