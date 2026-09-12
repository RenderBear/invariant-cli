from __future__ import annotations


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Invariant · State explorer</title>
  <link rel="stylesheet" href="/assets/app.css">
</head>
<body>
  <header class="masthead">
    <div class="brand">
      <pre class="wordmark" aria-label="Invariant">█ █▄ █ █ █ ▄▀▄ █▀▄ █ ▄▀▄ █▄ █ ▀█▀
█ █ ▀█ ▀▄▀ █▀█ █▀▄ █ █▀█ █ ▀█  █ </pre>
      <span>State explorer</span>
    </div>
    <div class="connection" aria-live="polite">
      <span id="stream-dot" class="stream-dot waiting"></span>
      <strong id="stream-state">CONNECTING</strong>
      <span id="observed-at" class="muted">loading workspace</span>
    </div>
  </header>

  <main class="workspace">
    <aside class="explorer-pane" aria-labelledby="explorer-title">
      <div class="pane-head"><p class="eyebrow">Machine</p><h1 id="explorer-title">Explorer</h1></div>
      <nav id="explorer" class="tree" aria-label="Project folders and session files"></nav>
      <div id="projects-empty" class="empty" hidden><p>No repositories registered.</p><code>invariant init</code></div>
      <p class="pane-note">Read-only view. Add projects and open sessions from the terminal.</p>
    </aside>

    <section class="work-pane" aria-labelledby="selection-title">
      <header class="work-head">
        <div>
          <p id="project-path" class="eyebrow path">Choose a project folder</p>
          <h2 id="selection-title">Repository lifecycle</h2>
          <p id="selection-meta" class="muted">Select a folder or session file in the explorer.</p>
        </div>
        <dl id="repository-facts" class="repository-facts"></dl>
      </header>

      <div id="notice" class="notice" role="status" hidden></div>

      <section id="selection-empty" class="selection-empty">
        <p class="eyebrow">State, not control</p>
        <h3>Choose a project folder to inspect its lifecycle.</h3>
        <p>Sessions appear as files and open as read-only logs.</p>
      </section>

      <section id="session-log" class="session-log" aria-labelledby="log-title" hidden>
        <div class="section-head">
          <div><p class="eyebrow">Session file</p><h3 id="log-title">Log entries</h3></div>
          <span class="tag">read only</span>
        </div>
        <div id="messages" class="messages"></div>
      </section>

      <section id="lifecycle" class="lifecycle" aria-labelledby="lifecycle-title" hidden>
        <div class="section-head">
          <div><p class="eyebrow">Repository state</p><h3 id="lifecycle-title">Lifecycle</h3></div>
          <span id="activity-count" class="counter">—</span>
        </div>
        <dl id="lifecycle-summary" class="lifecycle-summary"></dl>
        <div id="tasks" class="task-list"></div>
        <div id="signals" class="signal-grid"></div>
      </section>
    </section>
  </main>
  <script src="/assets/app.js" defer></script>
</body>
</html>
"""


CSS = """:root {
  color-scheme: dark;
  --paper: #191919; --surface: #202020;
  --ink: #e8e8e8; --muted: #8a8a8a;
  --line: #343434; --strong-line: #555555;
  --accent: #b48cf2; --ok: #25e04f;
  --warn: #e6b450; --bad: #ff6666;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
* { box-sizing: border-box; }
html, body { background: var(--paper); color: var(--ink); font-family: var(--sans); margin: 0; min-height: 100%; }
button { color: inherit; cursor: pointer; font: inherit; }
.masthead { align-items: center; background: var(--paper); border-bottom: 2px solid var(--strong-line); display: flex; height: 70px; justify-content: space-between; padding: 0 22px; }
.brand { align-items: center; display: flex; gap: 18px; }
.wordmark { color: var(--accent); font: 700 10px/1.05 var(--mono); margin: 0; white-space: pre; }
.brand > span { border-left: 1px solid var(--line); color: var(--muted); font: 10px var(--mono); letter-spacing: .08em; padding-left: 18px; text-transform: uppercase; }
.connection { align-items: center; display: flex; font: 10px var(--mono); gap: 8px; }
.stream-dot { border: 1px solid currentColor; display: block; height: 8px; width: 8px; }
.stream-dot.live { background: var(--ok); color: var(--ok); } .stream-dot.waiting { background: var(--warn); color: var(--warn); } .stream-dot.offline { background: var(--bad); color: var(--bad); }
.muted { color: var(--muted); }
.workspace { display: grid; grid-template-columns: 310px minmax(0, 1fr); min-height: calc(100vh - 70px); }
.explorer-pane { background: var(--surface); border-right: 1px solid var(--line); min-width: 0; padding: 24px 12px; }
.work-pane { min-width: 0; padding: 28px clamp(22px, 4vw, 54px) 54px; }
.pane-head { padding: 0 9px 18px; }
.eyebrow { color: var(--muted); font: 9px/1.4 var(--mono); letter-spacing: .08em; margin: 0 0 6px; text-transform: uppercase; }
h1, h2, h3 { letter-spacing: -.025em; margin: 0; } h1 { font-size: 24px; } h2 { font-size: 23px; } h3 { font-size: 17px; }
.path { max-width: 650px; overflow-wrap: anywhere; text-transform: none; }
.tree { display: grid; gap: 8px; }
.tree-project { min-width: 0; }
.tree-row { align-items: start; background: transparent; border: 1px solid transparent; display: grid; gap: 8px; grid-template-columns: 14px minmax(0, 1fr) auto; padding: 8px 9px; text-align: left; width: 100%; }
.tree-row:hover { border-color: var(--line); } .tree-row.active { background: var(--paper); border-color: var(--accent); }
.tree-row.active .tree-glyph { color: var(--accent); }
.tree-row.unavailable { color: var(--bad); }
.tree-glyph { color: var(--muted); font: 11px/1.5 var(--mono); }
.tree-label { display: block; font-size: 12px; line-height: 1.5; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tree-count, .file-meta { color: var(--muted); font: 8px/1.8 var(--mono); letter-spacing: .04em; text-transform: uppercase; }
.tree-children { border-left: 1px solid var(--line); margin-left: 15px; padding: 2px 0 2px 7px; }
.file-row { grid-template-columns: 14px minmax(0, 1fr); padding-bottom: 6px; padding-top: 6px; }
.file-copy { min-width: 0; } .file-copy .tree-label { font-family: var(--mono); font-size: 11px; }
.file-meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.live-mark { color: var(--ok); font-style: normal; margin-left: 5px; }
.empty { border: 1px dashed var(--line); color: var(--muted); font-size: 12px; line-height: 1.5; margin: 4px 9px; padding: 14px; }
.empty p { margin: 0; } .empty code { display: block; font: 9px/1.5 var(--mono); margin-top: 9px; overflow-wrap: anywhere; }
.pane-note { border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; line-height: 1.5; margin: 28px 9px 0; padding-top: 14px; }
.work-head { align-items: end; border-bottom: 1px solid var(--strong-line); display: flex; gap: 28px; justify-content: space-between; padding-bottom: 20px; }
.work-head > div { min-width: 0; } #selection-meta { font: 10px/1.5 var(--mono); margin: 8px 0 0; }
.repository-facts { display: grid; gap: 5px 14px; grid-template-columns: auto auto; margin: 0; min-width: 230px; }
.repository-facts dt { color: var(--muted); font: 9px var(--mono); text-transform: uppercase; } .repository-facts dd { font: 10px var(--mono); margin: 0; text-align: right; }
.notice { border: 1px solid var(--warn); color: var(--warn); font: 11px/1.5 var(--mono); margin-top: 18px; padding: 11px 13px; }
.notice.bad { border-color: var(--bad); color: var(--bad); }
.selection-empty { display: grid; min-height: 260px; place-content: center; text-align: center; }
.selection-empty h3 { font-size: clamp(20px, 3vw, 30px); line-height: 1.25; max-width: 570px; }
.selection-empty > p:last-child { color: var(--muted); font-size: 12px; }
.session-log { border-bottom: 1px solid var(--strong-line); padding: 28px 0 12px; }
.section-head { align-items: end; display: flex; justify-content: space-between; margin-bottom: 15px; }
.messages { display: grid; gap: 20px; padding: 8px 0 22px; }
.message { display: grid; gap: 7px; grid-template-columns: 90px minmax(0, 760px); }
.message .role { color: var(--muted); font: 9px/1.6 var(--mono); padding-top: 2px; text-transform: uppercase; }
.message .content { font-size: 14px; line-height: 1.65; margin: 0; white-space: pre-wrap; } .message.user .role { color: var(--accent); }
.message.system .content { color: var(--muted); font-family: var(--mono); font-size: 11px; } .message.failed .content { color: var(--bad); }
.lifecycle { padding-top: 32px; }
.counter, .tag { border: 1px solid currentColor; color: var(--muted); font: 8px var(--mono); padding: 4px 6px; text-transform: uppercase; }
.counter { border-color: var(--line); font-size: 10px; padding: 5px 8px; }
.tag.ok { color: var(--ok); } .tag.warn { color: var(--warn); } .tag.bad { color: var(--bad); }
.lifecycle-summary { border-bottom: 1px solid var(--line); border-top: 1px solid var(--line); display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 0 0 18px; }
.lifecycle-summary > div { border-right: 1px solid var(--line); padding: 12px; } .lifecycle-summary > div:last-child { border-right: 0; }
.lifecycle-summary dt { color: var(--muted); font: 8px var(--mono); text-transform: uppercase; } .lifecycle-summary dd { font: 18px var(--mono); margin: 5px 0 0; }
.task-list { display: grid; gap: 9px; }
.task { border: 1px solid var(--line); padding: 13px 15px; } .task.ok { border-color: var(--ok); } .task.attention { border-color: var(--warn); } .task.bad { border-color: var(--bad); }
.task-head { align-items: baseline; display: flex; gap: 12px; justify-content: space-between; } .task-head strong { font-size: 12px; overflow-wrap: anywhere; }
.task-meta { color: var(--muted); display: flex; flex-wrap: wrap; font: 9px/1.5 var(--mono); gap: 4px 14px; margin-top: 9px; }
.activity-empty { border: 1px dashed var(--line); color: var(--muted); font-size: 12px; margin: 0; padding: 16px; }
.signal-grid { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 18px; }
.signal { border-top: 1px solid var(--strong-line); padding-top: 12px; }
.signal-head { align-items: baseline; display: flex; justify-content: space-between; } .signal-head h4 { font-size: 11px; margin: 0; text-transform: uppercase; }
.signal-head span { color: var(--muted); font: 9px var(--mono); }
.signal ul { list-style: none; margin: 9px 0 0; padding: 0; }
.signal li { border-top: 1px solid var(--line); display: grid; font: 10px/1.45 var(--mono); gap: 10px; grid-template-columns: minmax(0, 1fr) auto; padding: 7px 0; }
.signal li span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .signal-empty { color: var(--muted); }
@media (max-width: 900px) { .workspace { grid-template-columns: 260px minmax(0, 1fr); } .work-pane { padding-left: 24px; padding-right: 24px; } .repository-facts { display: none; } }
@media (max-width: 680px) { .masthead { height: 60px; padding: 0 14px; } .wordmark { font-size: 8px; } .brand > span, #observed-at { display: none; } .workspace { display: block; min-height: calc(100vh - 60px); } .explorer-pane { border-bottom: 1px solid var(--line); border-right: 0; max-height: 42vh; overflow-y: auto; padding: 15px 10px; } .pane-note { display: none; } .work-pane { padding: 22px 16px 40px; } .message { grid-template-columns: 62px minmax(0, 1fr); } .lifecycle-summary { grid-template-columns: repeat(3, 1fr); } .lifecycle-summary > div { border-bottom: 1px solid var(--line); } .signal-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
"""


JS = r"""const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const short = (value, size = 10) => value ? String(value).slice(0, size) : "—";
let workspaceState = {projects: [], sessions: []};
let selectedProject = localStorage.getItem("invariant.project") || "";
let selectedSession = localStorage.getItem("invariant.session") || "";
let repositorySnapshot = null; let activeSession = null; let events = null; let connectedProject = "";

function tone(value) { const state = String(value || "").toLowerCase(); if (["fresh", "valid", "passed", "complete", "landed", "live", "running", "accepted"].some(x => state.includes(x))) return "ok"; if (["stale", "invalid", "failed", "error", "diverged", "expired", "rejected"].some(x => state.includes(x))) return "bad"; if (["waiting", "review", "implement", "planning", "checking", "active", "uncertain"].some(x => state.includes(x))) return "warn"; return ""; }
function streamState(state, detail = "") { $("stream-state").textContent = state; $("stream-dot").className = `stream-dot ${state === "LIVE" ? "live" : state === "OFFLINE" ? "offline" : "waiting"}`; if (detail) $("observed-at").textContent = detail; }
function notice(message = "", bad = false) { $("notice").hidden = !message; $("notice").textContent = message; $("notice").className = `notice ${bad ? "bad" : ""}`; }
function projectSessions(projectId) { return (workspaceState.sessions || []).filter(item => item.project_id === projectId); }
function currentProject() { return (workspaceState.projects || []).find(item => item.id === selectedProject) || null; }
function currentSession() { return activeSession?.id === selectedSession ? activeSession : (workspaceState.sessions || []).find(item => item.id === selectedSession) || null; }
function fileName(theme) { return `${String(theme || "untitled").replaceAll("/", "-")}.session`; }

function normalizeSelection() {
  const projects = workspaceState.projects || [];
  const selected = (workspaceState.sessions || []).find(item => item.id === selectedSession);
  if (selected) selectedProject = selected.project_id;
  if (!projects.some(item => item.id === selectedProject)) selectedProject = projects[0]?.id || "";
  if (selectedSession && !projectSessions(selectedProject).some(item => item.id === selectedSession)) selectedSession = "";
}
function renderExplorer() {
  normalizeSelection(); const projects = workspaceState.projects || []; $("projects-empty").hidden = projects.length !== 0;
  $("explorer").innerHTML = projects.map(project => {
    const sessions = projectSessions(project.id); const available = project.available && project.initialized;
    const files = sessions.length ? sessions.map(session => `<button type="button" class="tree-row file-row ${session.id === selectedSession ? "active" : ""}" data-project="${esc(project.id)}" data-session="${esc(session.id)}"><span class="tree-glyph">◇</span><span class="file-copy"><span class="tree-label">${esc(fileName(session.theme))}${session.live ? '<em class="live-mark">●</em>' : ''}</span><span class="file-meta">${esc(session.mode)} · ${esc(session.message_count ?? 0)} entries</span></span></button>`).join("") : `<div class="tree-row file-row"><span class="tree-glyph">·</span><span class="file-copy"><span class="file-meta">no session files</span></span></div>`;
    return `<section class="tree-project"><button type="button" class="tree-row folder-row ${project.id === selectedProject && !selectedSession ? "active" : ""} ${available ? "" : "unavailable"}" data-project="${esc(project.id)}"><span class="tree-glyph">▾</span><strong class="tree-label">${esc(project.name)}/</strong><span class="tree-count">${available ? sessions.length : "offline"}</span></button><div class="tree-children">${files}</div></section>`;
  }).join("");
  $("explorer").querySelectorAll(".folder-row[data-project]").forEach(button => button.addEventListener("click", () => selectProject(button.dataset.project)));
  $("explorer").querySelectorAll("[data-session]").forEach(button => button.addEventListener("click", () => selectSession(button.dataset.project, button.dataset.session)));
}
function renderSelection() {
  const project = currentProject(); const session = currentSession(); $("project-path").textContent = project?.path || "Choose a project folder";
  $("selection-empty").hidden = Boolean(project); $("session-log").hidden = !session; $("lifecycle").hidden = !project;
  if (!project) { $("selection-title").textContent = "Repository lifecycle"; $("selection-meta").textContent = "Select a folder or session file in the explorer."; return; }
  if (!session) { $("selection-title").textContent = `${project.name}/`; $("selection-meta").textContent = "Project folder · live repository projection"; return; }
  $("selection-title").textContent = fileName(session.theme); $("selection-meta").textContent = `${session.id} · ${session.mode} · ${session.provider || "no provider yet"} · updated ${session.updated_at || "unknown"}`;
  const messages = session.messages || [];
  $("messages").innerHTML = messages.length ? messages.map(message => `<article class="message ${esc(message.role)} ${message.state === "failed" ? "failed" : ""}"><span class="role">${esc(message.role)}</span><p class="content">${esc(message.content)}</p></article>`).join("") : `<article class="message system"><span class="role">Empty</span><p class="content">No recorded turns in this session file.</p></article>`;
}
function signal(title, items, label, state) {
  const rows = items.slice(0, 6).map(item => `<li><span>${esc(label(item))}</span><span class="tag ${tone(state(item))}">${esc(state(item) || "recorded")}</span></li>`).join("");
  return `<section class="signal"><div class="signal-head"><h4>${esc(title)}</h4><span>${items.length}</span></div><ul>${rows || '<li class="signal-empty"><span>none</span></li>'}</ul></section>`;
}
function renderRepository() {
  const project = currentProject(); const repo = repositorySnapshot?.repository || {};
  const audit = repositorySnapshot?.governance?.audit || {};
  $("repository-facts").innerHTML = repo.name ? [["Branch", repo.branch || "detached"], ["Head", short(repo.head)], ["State", repo.state || "unknown"], ["Intent", repo.intent || repo.authority || "—"], ["Resolution", repo.resolution || "—"], ["Execution", "parallel agents"], ["Audit", audit.id ? `${audit.id} · ${audit.status}` : "none"]].map(([name, value]) => `<dt>${esc(name)}</dt><dd>${esc(value)}</dd>`).join("") : "";
  if (!project || !repositorySnapshot) { $("lifecycle-summary").innerHTML = ""; $("tasks").innerHTML = '<p class="activity-empty">Loading repository state…</p>'; $("signals").innerHTML = ""; return; }
  const tasks = repositorySnapshot.tasks || []; const plans = repositorySnapshot.plans || []; const leases = repositorySnapshot.leases || []; const processes = repositorySnapshot.processes || []; const evidence = repositorySnapshot.evidence || []; const records = repositorySnapshot.governance?.records || [];
  $("activity-count").textContent = `${tasks.length} active`;
  $("lifecycle-summary").innerHTML = [["Tasks", tasks.length], ["Plans", plans.length], ["Leases", leases.length], ["Records", records.length], ["Evidence", evidence.length]].map(([name, value]) => `<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`).join("");
  $("tasks").innerHTML = tasks.length ? tasks.map(item => { const state = item.freshness || item.stage; const stateTone = tone(state); return `<article class="task ${stateTone === "ok" ? "ok" : stateTone === "bad" ? "bad" : stateTone === "warn" ? "attention" : ""}"><div class="task-head"><strong>${esc(item.id)}</strong><span class="tag ${tone(item.stage)}">${esc(item.stage)}</span></div><div class="task-meta"><span>${esc(item.kind)}</span><span>${esc(item.freshness)}</span><span>target ${esc(item.target || "—")}</span><span>${esc(item.pending_actions)} pending</span></div></article>`; }).join("") : `<p class="activity-empty">No active changes. Repository mechanics are ready.</p>`;
  $("signals").innerHTML = [
    signal("Governance", records, item => item.id, item => "accepted"),
    signal("Plans", plans, item => item.summary || item.id, item => item.valid ? "valid" : "invalid"),
    signal("Leases", leases, item => item.unit, item => item.state),
    signal("Processes", processes, item => item.task || item.command, item => item.state),
    signal("Recent evidence", evidence, item => item.summary || item.id, item => item.freshness || item.status)
  ].join("");
  const diagnostics = [...(repositorySnapshot.diagnostics || []), ...(repositorySnapshot.governance?.diagnostics || [])]; notice(diagnostics.join(" · "), diagnostics.length > 0);
}
function renderAll() { renderExplorer(); renderSelection(); renderRepository(); }

async function loadState({quiet = false} = {}) {
  try {
    const response = await fetch("/host/v1/state", {cache: "no-store"}); if (!response.ok) throw new Error(`HTTP ${response.status}`);
    workspaceState = await response.json(); normalizeSelection(); renderAll();
    const summary = (workspaceState.sessions || []).find(item => item.id === selectedSession); const changed = summary && summary.updated_at !== activeSession?.updated_at;
    if (!summary) { activeSession = null; renderSelection(); } else if (!activeSession || changed) await loadSession();
    if (!quiet || selectedProject !== connectedProject) connectProject();
  } catch (error) { streamState("OFFLINE", `workspace unavailable · ${error.message}`); }
}
async function loadSession() {
  if (!selectedSession) { activeSession = null; renderSelection(); return; }
  try { const response = await fetch(`/host/v1/sessions/${encodeURIComponent(selectedSession)}`, {cache: "no-store"}); const value = await response.json(); if (!response.ok) throw new Error(value.message || `HTTP ${response.status}`); activeSession = value.session; renderSelection(); }
  catch (error) { activeSession = null; notice(error.message, true); }
}
async function loadProjectSnapshot() {
  repositorySnapshot = null; renderRepository(); if (!selectedProject) return;
  try { const response = await fetch(`/host/v1/projects/${encodeURIComponent(selectedProject)}/snapshot`, {cache: "no-store"}); const value = await response.json(); if (!response.ok) throw new Error(value.message || `HTTP ${response.status}`); repositorySnapshot = value; renderRepository(); }
  catch (error) { notice(error.message, true); }
}
function connectProject() {
  if (events) events.close(); events = null; connectedProject = selectedProject; if (!selectedProject) { streamState("LIVE", "no project selected"); return; } loadProjectSnapshot();
  events = new EventSource(`/host/v1/projects/${encodeURIComponent(selectedProject)}/events`);
  events.addEventListener("open", () => streamState("LIVE"));
  events.addEventListener("snapshot", event => { try { repositorySnapshot = JSON.parse(event.data); renderRepository(); streamState("LIVE", repositorySnapshot.observed_at ? `observed ${repositorySnapshot.observed_at}` : "snapshot received"); } catch (error) { streamState("RECONNECTING", `invalid event · ${error.message}`); } });
  events.addEventListener("error", () => streamState("RECONNECTING", "waiting for project observer"));
}
function selectProject(identifier) { selectedProject = identifier; selectedSession = ""; activeSession = null; localStorage.setItem("invariant.project", selectedProject); localStorage.removeItem("invariant.session"); notice(); renderAll(); connectProject(); }
function selectSession(projectIdentifier, sessionIdentifier) { selectedProject = projectIdentifier; selectedSession = sessionIdentifier; activeSession = null; localStorage.setItem("invariant.project", selectedProject); localStorage.setItem("invariant.session", selectedSession); notice(); renderAll(); loadSession(); if (selectedProject !== connectedProject) connectProject(); }
loadState(); window.setInterval(() => loadState({quiet: true}), 3000);
"""
