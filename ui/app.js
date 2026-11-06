"use strict";
/* 对话居中、工具调用 trace 在右栏 —— 结论与过程分开看，输入框永远在。 */

const $ = (id) => document.getElementById(id);
const stream = $("stream");            // 中栏：对话与结论
const traceList = $("trace-list");     // 右栏：工具调用 trace
let running = false;
let evtSource = null;
let lastStep = 0;
let assistantBuf = "";

/* 极简 markdown：标题 / 加粗 / 行内码 / 列表 / 表格 —— 依赖为零，够聊天用 */
function mdToHtml(src) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => esc(s)
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  let html = "", inList = false, inTable = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const line of src.split("\n")) {
    const t = line.trim();
    if (/^\|.*\|$/.test(t)) {
      if (/^\|[\s:|-]+\|$/.test(t)) continue;            // 表头分隔行
      if (!inTable) { html += "<table>"; inTable = true; }
      html += "<tr>" + t.slice(1, -1).split("|")
        .map((c) => `<td>${inline(c.trim())}</td>`).join("") + "</tr>";
      continue;
    }
    closeList();
    if (inTable) { html += "</table>"; inTable = false; }
    if (/^#{1,4}\s/.test(t)) html += `<h4>${inline(t.replace(/^#+\s/, ""))}</h4>`;
    else if (/^[-*]\s/.test(t)) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(t.slice(2))}</li>`; }
    else if (/^\d+\.\s/.test(t)) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(t.replace(/^\d+\.\s/, ""))}</li>`; }
    else if (!t) html += "";
    else html += `<p>${inline(line)}</p>`;
  }
  closeList();
  if (inTable) html += "</table>";
  return html;
}

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

/* ---------- 文件查看（弹窗） ---------- */
async function openFile(path) {
  $("file-title").textContent = path;
  $("file-view").textContent = "加载中…";
  $("file-modal").classList.remove("hidden");
  const res = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  $("file-view").textContent = data.ok ? data.output : (data.output || "读取失败");
}

/* ---------- 右栏：工具调用 trace ---------- */
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
const scrollDown = () => { stream.scrollTop = stream.scrollHeight; };
const scrollTrace = () => { traceList.scrollTop = traceList.scrollHeight; };

/* 长回答常是一次性整块进 DOM：排版前读 scrollHeight 偏小，滚一次会停在半路。
   运行期间用定时器持续跟随，保证「最新内容永远可见」；任务结束即停。 */
let followTimer = null;
function startFollow() {
  stopFollow();
  scrollDown();
  followTimer = setInterval(() => { scrollDown(); scrollTrace(); }, 300);
}
function stopFollow() { if (followTimer) { clearInterval(followTimer); followTimer = null; } }

const pendingCalls = new Map();        // call_id -> 运行中的卡片，tool_end 时替换

function tracePlaceholder() {
  const p = el("div", "trace-empty", "任务开始后，每个工具调用会实时出现在这里");
  traceList.appendChild(p);
}
function dropTracePlaceholder() {
  const p = traceList.querySelector(".trace-empty");
  if (p) p.remove();
}

function toolHeader(tool, ok, ms) {
  const isMcp = tool.startsWith("mcp__");
  const head = el("div", "tc-head");
  const name = el("span", "tc-name");
  if (isMcp) {
    name.appendChild(el("span", "mcp-tag", "MCP"));
    name.appendChild(document.createTextNode(tool.replace(/^mcp__/, "").replace("__", " · ")));
  } else {
    name.textContent = tool;
  }
  head.appendChild(name);
  head.appendChild(el("span", "tc-status", ok === null ? "运行中" : ok ? "成功" : "失败"));
  if (ms !== null) head.appendChild(el("span", "tc-ms", `${ms}ms`));
  return head;
}

function addToolBegin(ev) {
  dropTracePlaceholder();
  $("activity").textContent = `第 ${lastStep || "?"} 步 · 正在执行 ${ev.tool}…`;
  const card = el("div", "tool-card pending");
  card.appendChild(toolHeader(ev.tool, null, null));
  if (ev.args && ev.args !== "{}") {
    card.appendChild(el("div", "tc-args", ev.args.length > 100 ? ev.args.slice(0, 100) + "…" : ev.args));
  }
  pendingCalls.set(ev.call_id, card);
  traceList.appendChild(card);
  scrollTrace();
}

function addToolCard(ev) {
  const card = el("div", `tool-card ${ev.ok ? "ok" : "fail"}`);
  card.appendChild(toolHeader(ev.tool, ev.ok, ev.elapsed_ms || 0));

  if (ev.error) card.appendChild(el("div", "tc-meta", ev.error));

  // 输出默认折叠，点卡片展开 —— trace 栏保持一览性
  const out = ev.output || "";
  const pre = el("pre", "collapsed");
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
  card.onclick = () => pre.classList.toggle("collapsed");
  card.appendChild(pre);

  const pending = pendingCalls.get(ev.call_id);
  if (pending) { pending.replaceWith(card); pendingCalls.delete(ev.call_id); }
  else traceList.appendChild(card);
  $("activity").textContent = "";
  scrollTrace();
}

/* ---------- 中栏：对话状态 ---------- */
function setRunning(v) {
  running = v;
  $("btn-send").disabled = v;
  $("btn-stop").disabled = !v;
  $("run-badge").classList.toggle("hidden", !v);
  $("run-badge").classList.toggle("on", v);
}

function runTask(task) {
  if (running || !task.trim()) return;
  setRunning(true);
  pendingCalls.clear();
  if (!traceList.querySelector(".trace-empty") && !traceList.querySelector(".tool-card")) tracePlaceholder();
  stream.appendChild(el("div", "msg user", task));
  const typing = el("div", "typing", "思考中…");
  stream.appendChild(typing);
  scrollDown();

  let current = null;                                // 当前正在流的 assistant 气泡
  const q = `task=${encodeURIComponent(task)}` +
            `&skills=${$("tg-skills").checked ? 1 : 0}` +
            `&hooks=${$("tg-hooks").checked ? 1 : 0}`;
  evtSource = new EventSource(`/api/run/stream?${q}`);
  startFollow();
  evtSource.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "__done__") { evtSource.close(); stopFollow(); setRunning(false); typing.remove(); scrollDown(); return; }
    if (ev.type === "capabilities") {
      $("caps-line").textContent =
        `技能 ${ev.skills.length} 个${ev.skills.length ? "（" + ev.skills.join("/") + "）" : ""}` +
        ` · 钩子 ${ev.hooks ? "on" : "off"} · AGENTS.md ${ev.agents_md.join("/") || "无"}`;
      return;
    }
    if (ev.type === "provider") {
      $("provider-badge").textContent = ev.name === "deepseek" ? "模型 · DeepSeek" : "模型 · 离线 mock";
      $("provider-badge").classList.toggle("warn", ev.name !== "deepseek");
      setModelBadge(ev.name === "deepseek" ? "deepseek-chat" : "", ev.name !== "deepseek");
      if (ev.name !== "deepseek") typing.textContent = "未配置 Key，走离线 mock 演示…";
      return;
    }
    if (ev.type === "assistant_text") {
      typing.remove();
      $("activity").textContent = "模型思考中…";
      if (!current) { current = el("div", "msg assistant"); stream.appendChild(current); assistantBuf = ""; }
      assistantBuf += ev.delta;
      current.innerHTML = mdToHtml(assistantBuf);   // 按聊天软件那样渲染 markdown
      requestAnimationFrame(scrollDown);
      return;
    }
    current = null;
    assistantBuf = "";
    if (ev.type === "step_begin") lastStep = ev.step;
    else if (ev.type === "tool_begin") addToolBegin(ev);
    else if (ev.type === "tool_end") addToolCard(ev);
    else if (ev.type === "final") {
      stream.appendChild(el("div", "final-line", "✓ 任务完成"));
      $("activity").textContent = "";
    }
    else if (ev.type === "stopped") { stream.appendChild(el("div", "stopped-line", `■ 停止：${ev.reason}`)); $("activity").textContent = ""; }
    else if (ev.type === "error") { stream.appendChild(el("div", "error-line", ev.message)); $("activity").textContent = ""; }
    scrollDown();
  };
  evtSource.onerror = () => {
    typing.remove();
    if (running) stream.appendChild(el("div", "stopped-line", "连接结束"));
    evtSource.close();
    stopFollow();
    setRunning(false);
    scrollDown();
  };
}

/* 顶栏模型徽标：有 Key 显示模型名（绿点在线），没有则黄点离线 */
function setModelBadge(model, offline) {
  const b = $("model-badge");
  b.textContent = offline ? "离线 mock" : `模型 · ${model}`;
  b.classList.toggle("on", !offline);
}

/* 运行中提示：输入框常驻可打字，只是发送键暂时不可用 */
function flashHint(text) {
  if ($(".flash-hint")) return;
  const hint = el("div", "flash-hint", text);
  stream.appendChild(hint);
  scrollDown();
  setTimeout(() => hint.remove(), 3000);
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
  setModelBadge(cfg.has_key ? (cfg.model || "deepseek-chat") : "", !cfg.has_key);
  const ok = (cfg.mcp || []).filter(s => s.ok).length;
  const total = (cfg.mcp || []).length;
  const badge = $("mcp-badge");
  badge.textContent = total ? `MCP · ${ok}/${total} server 在线` : "MCP · 无配置";
  badge.className = "badge " + (ok ? "mcp-on" : "mcp-off");
  badge.title = (cfg.mcp || []).map(s => `${s.server}: ${s.ok ? "ok" : s.error}`).join("\n");
}

/* ---------- 绑定 ---------- */
$("btn-send").onclick = () => {
  if (running) { flashHint("任务运行中——点 ■ 停止 可中断，结束后再发"); return; }
  runTask($("task-input").value); $("task-input").value = "";
};
$("task-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (running) { flashHint("任务运行中——点 ■ 停止 可中断，结束后再发"); return; }
    runTask($("task-input").value); $("task-input").value = "";
  }
});
$("btn-stop").onclick = async () => { await fetch("/api/interrupt", { method: "POST" }); };
$("btn-new").onclick = async () => {
  if (running) await fetch("/api/interrupt", { method: "POST" });
  stopFollow();
  stream.innerHTML = "";
  $("caps-line").textContent = "";
  $("task-input").value = "";
  $("task-input").focus();
};
$("btn-clear-trace").onclick = () => { traceList.innerHTML = ""; };
$("btn-settings").onclick = openSettings;
$("cfg-cancel").onclick = () => $("settings-modal").classList.add("hidden");
$("cfg-save").onclick = saveSettings;
$("file-close").onclick = () => $("file-modal").classList.add("hidden");

loadTree();
refreshBadges();
tracePlaceholder();
