from __future__ import annotations


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Invariant · Local workspace</title>
  <link rel="stylesheet" href="/assets/app.css">
</head>
<body>
  <header class="masthead">
    <div class="brand">
      <pre class="wordmark" aria-label="Invariant">█ █▄ █ █ █ ▄▀▄ █▀▄ █ ▄▀▄ █▄ █ ▀█▀
█ █ ▀█ ▀▄▀ █▀█ █▀▄ █ █▀█ █ ▀█  █ </pre>
      <span>Local workspace</span>
    </div>
    <div class="connection" aria-live="polite">
      <span id="stream-dot" class="stream-dot waiting"></span>
      <strong id="stream-state">CONNECTING</strong>
      <span id="observed-at" class="muted">loading projects</span>
    </div>
  </header>

  <main class="workspace">
    <aside class="projects-pane" aria-labelledby="projects-title">
      <div class="pane-head"><p class="eyebrow">Machine</p><h1 id="projects-title">Projects</h1></div>
      <nav id="projects" class="nav-list" aria-label="Registered projects"></nav>
      <div id="projects-empty" class="empty" hidden><p>No repositories registered.</p><code>invariant init</code></div>
      <p class="pane-note">Folders are registered explicitly. Invariant never scans this computer.</p>
    </aside>

    <aside class="sessions-pane" aria-labelledby="sessions-title">
      <div class="pane-head session-heading">
        <div><p class="eyebrow">Project themes</p><h2 id="sessions-title">Sessions</h2></div>
        <button id="new-session-toggle" class="quiet-button" type="button">New</button>
      </div>
      <form id="new-session-form" class="new-session" hidden>
        <label for="session-theme">Theme</label>
        <input id="session-theme" name="theme" maxlength="80" placeholder="Authentication redesign" required>
        <div class="form-row">
          <select id="session-mode" name="mode" aria-label="Session mode"><option value="ask">Ask</option><option value="change">Change</option></select>
          <button class="primary-button" type="submit">Create</button>
        </div>
      </form>
      <nav id="sessions" class="nav-list sessions-list" aria-label="Project sessions"></nav>
      <div id="sessions-empty" class="empty" hidden><p>No sessions yet.</p></div>
    </aside>

    <section class="work-pane" aria-labelledby="session-title">
      <header class="work-head">
        <div><p id="project-path" class="eyebrow path">Choose a project</p><h2 id="session-title">Open a session</h2><p id="session-meta" class="muted">Sessions keep one theme grounded in one folder.</p></div>
        <dl id="repository-facts" class="repository-facts"></dl>
      </header>
      <div id="notice" class="notice" role="status" hidden></div>
      <div id="conversation-empty" class="conversation-empty"><p class="eyebrow">One folder · one theme</p><h3>Choose a session, or create one for the work you want to keep together.</h3></div>
      <section id="conversation" class="conversation" aria-label="Conversation" hidden>
        <div id="messages" class="messages" aria-live="polite"></div>
        <form id="composer" class="composer">
          <label class="sr-only" for="prompt">Message</label>
          <textarea id="prompt" rows="3" placeholder="Ask about this project…" required></textarea>
          <div class="composer-foot"><span id="composer-scope">Read-only conversation</span><button id="send" class="primary-button" type="submit">Send</button></div>
        </form>
      </section>
      <section class="activity" aria-labelledby="activity-title">
        <div class="activity-head"><div><p class="eyebrow">Repository lifecycle</p><h3 id="activity-title">Activity</h3></div><span id="activity-count" class="counter">—</span></div>
        <div id="tasks" class="task-list"></div>
      </section>
    </section>
  </main>
  <script src="/assets/app.js" defer></script>
</body>
</html>
"""


CSS = """:root {
  color-scheme: light dark;
  --paper: light-dark(#ffffff, #151515); --surface: light-dark(#f5f5f2, #1d1d1b);
  --ink: light-dark(#171717, #f0f0eb); --muted: light-dark(#656560, #a3a39c);
  --line: light-dark(#c8c8c1, #42423d); --strong-line: light-dark(#202020, #deded7);
  --accent: light-dark(#007f92, #49c2d2); --ok: light-dark(#237a3b, #63c77b);
  --warn: light-dark(#986800, #e2b64d); --bad: light-dark(#b42318, #ff796f);
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
* { box-sizing: border-box; }
html, body { background: var(--paper); color: var(--ink); font-family: var(--sans); margin: 0; min-height: 100%; }
button, input, select, textarea { color: inherit; font: inherit; } button { cursor: pointer; }
.masthead { align-items: center; background: var(--paper); border-bottom: 2px solid var(--strong-line); display: flex; height: 70px; justify-content: space-between; padding: 0 22px; }
.brand { align-items: center; display: flex; gap: 18px; }
.wordmark { color: var(--accent); font: 700 10px/1.05 var(--mono); margin: 0; white-space: pre; }
.brand > span { border-left: 1px solid var(--line); color: var(--muted); font: 10px var(--mono); letter-spacing: .08em; padding-left: 18px; text-transform: uppercase; }
.connection { align-items: center; display: flex; font: 10px var(--mono); gap: 8px; }
.stream-dot { border: 1px solid currentColor; display: block; height: 8px; width: 8px; }
.stream-dot.live { background: var(--ok); color: var(--ok); } .stream-dot.waiting { background: var(--warn); color: var(--warn); } .stream-dot.offline { background: var(--bad); color: var(--bad); }
.muted { color: var(--muted); }
.workspace { display: grid; grid-template-columns: 220px 280px minmax(0, 1fr); min-height: calc(100vh - 70px); }
.projects-pane, .sessions-pane { border-right: 1px solid var(--line); min-width: 0; padding: 24px 14px; }
.sessions-pane { background: var(--surface); } .nav-item em.live { font-style: normal; font-size: 10px; letter-spacing: .08em; text-transform: uppercase; margin-left: 6px; color: var(--accent, #2a7); } .work-pane { min-width: 0; padding: 28px clamp(22px, 4vw, 54px) 54px; }
.pane-head { padding: 0 8px 20px; } .session-heading { align-items: end; display: flex; justify-content: space-between; }
.eyebrow { color: var(--muted); font: 9px/1.4 var(--mono); letter-spacing: .08em; margin: 0 0 6px; text-transform: uppercase; }
h1, h2, h3 { letter-spacing: -.025em; margin: 0; } h1 { font-size: 24px; } h2 { font-size: 23px; } h3 { font-size: 17px; }
.path { max-width: 650px; overflow-wrap: anywhere; text-transform: none; }
.nav-list { display: grid; gap: 2px; }
.nav-item { background: transparent; border: 1px solid transparent; display: block; padding: 11px 10px; text-align: left; width: 100%; }
.nav-item:hover { border-color: var(--line); } .nav-item.active { background: var(--paper); border-color: var(--strong-line); }
.nav-item strong { display: block; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nav-item span { color: var(--muted); display: block; font: 9px/1.5 var(--mono); margin-top: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nav-item.unavailable strong { color: var(--bad); }
.pane-note { border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; line-height: 1.5; margin: 28px 8px 0; padding-top: 14px; }
.empty { border: 1px dashed var(--line); color: var(--muted); font-size: 12px; line-height: 1.5; margin: 4px 8px; padding: 14px; }
.empty p { margin: 0; } .empty code { display: block; font: 9px/1.5 var(--mono); margin-top: 9px; overflow-wrap: anywhere; }
.quiet-button, .primary-button { border: 1px solid var(--strong-line); padding: 7px 11px; }
.quiet-button { background: transparent; font: 10px var(--mono); } .primary-button { background: var(--ink); color: var(--paper); font: 700 10px var(--mono); text-transform: uppercase; }
.quiet-button:hover, .primary-button:hover { border-color: var(--accent); color: var(--accent); } .primary-button:disabled { cursor: wait; opacity: .5; }
.new-session { border-bottom: 1px solid var(--line); display: grid; gap: 8px; margin: 0 8px 12px; padding-bottom: 16px; }
.new-session label { color: var(--muted); font: 9px var(--mono); text-transform: uppercase; }
input, select, textarea { background: var(--paper); border: 1px solid var(--line); border-radius: 0; outline: none; padding: 9px 10px; }
input:focus, select:focus, textarea:focus { border-color: var(--accent); } .form-row { display: grid; gap: 8px; grid-template-columns: 1fr auto; }
.work-head { align-items: end; border-bottom: 1px solid var(--strong-line); display: flex; gap: 28px; justify-content: space-between; padding-bottom: 20px; }
.work-head > div { min-width: 0; } #session-meta { font: 10px/1.5 var(--mono); margin: 8px 0 0; }
.repository-facts { display: grid; gap: 5px 14px; grid-template-columns: auto auto; margin: 0; min-width: 230px; }
.repository-facts dt { color: var(--muted); font: 9px var(--mono); text-transform: uppercase; } .repository-facts dd { font: 10px var(--mono); margin: 0; text-align: right; }
.notice { border: 1px solid var(--warn); color: var(--warn); font: 11px/1.5 var(--mono); margin-top: 18px; padding: 11px 13px; }
.notice.bad { border-color: var(--bad); color: var(--bad); }
.conversation-empty { display: grid; min-height: 360px; place-content: center; text-align: center; }
.conversation-empty h3 { font-size: clamp(20px, 3vw, 30px); line-height: 1.25; max-width: 570px; }
.conversation { border-bottom: 1px solid var(--strong-line); } .messages { display: grid; gap: 26px; min-height: 320px; padding: 34px 0; }
.message { display: grid; gap: 7px; grid-template-columns: 82px minmax(0, 720px); }
.message .role { color: var(--muted); font: 9px/1.6 var(--mono); padding-top: 2px; text-transform: uppercase; }
.message .content { font-size: 14px; line-height: 1.65; margin: 0; white-space: pre-wrap; } .message.user .role { color: var(--accent); }
.message.system .content { color: var(--muted); font-family: var(--mono); font-size: 11px; } .message.failed .content { color: var(--bad); }
.composer { border-top: 1px solid var(--line); padding: 18px 0 22px; } .composer textarea { display: block; line-height: 1.5; resize: vertical; width: 100%; }
.composer-foot { align-items: center; color: var(--muted); display: flex; font: 9px var(--mono); justify-content: space-between; margin-top: 9px; }
.activity { padding-top: 32px; } .activity-head { align-items: end; display: flex; justify-content: space-between; margin-bottom: 15px; }
.counter { border: 1px solid var(--line); font: 10px var(--mono); padding: 5px 8px; } .task-list { display: grid; gap: 9px; }
.task { border: 1px solid var(--line); padding: 13px 15px; } .task.attention { border-color: var(--warn); } .task.bad { border-color: var(--bad); }
.task-head { align-items: baseline; display: flex; gap: 12px; justify-content: space-between; } .task-head strong { font-size: 12px; overflow-wrap: anywhere; }
.tag { border: 1px solid currentColor; color: var(--muted); font: 8px var(--mono); padding: 3px 5px; text-transform: uppercase; }
.tag.ok { color: var(--ok); } .tag.warn { color: var(--warn); } .tag.bad { color: var(--bad); }
.task-meta { color: var(--muted); display: flex; flex-wrap: wrap; font: 9px/1.5 var(--mono); gap: 4px 14px; margin-top: 9px; }
.activity-empty { color: var(--muted); font-size: 12px; margin: 0; padding: 16px 0; }
.sr-only { clip: rect(0, 0, 0, 0); height: 1px; margin: -1px; overflow: hidden; padding: 0; position: absolute; width: 1px; }
@media (max-width: 900px) { .workspace { grid-template-columns: 190px 240px minmax(0, 1fr); } .work-pane { padding-left: 24px; padding-right: 24px; } .repository-facts { display: none; } }
@media (max-width: 680px) { .masthead { height: 60px; padding: 0 14px; } .wordmark { font-size: 8px; } .brand > span, #observed-at { display: none; } .workspace { display: block; min-height: calc(100vh - 60px); } .projects-pane, .sessions-pane { border-bottom: 1px solid var(--line); border-right: 0; padding: 15px 10px; } .nav-list { display: flex; overflow-x: auto; } .nav-item { flex: 0 0 170px; } .pane-note { display: none; } .work-pane { padding: 22px 16px 40px; } .message { grid-template-columns: 58px minmax(0, 1fr); } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
"""


JS = r"""const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const short = (value, size = 10) => value ? String(value).slice(0, size) : "—";
let workspaceState = {projects: [], sessions: []}; let token = "";
let selectedProject = localStorage.getItem("invariant.project") || ""; let selectedSession = localStorage.getItem("invariant.session") || "";
let repositorySnapshot = null; let activeSession = null; let events = null; let connectedProject = "";

function tone(value) { const state = String(value || "").toLowerCase(); if (["fresh", "valid", "passed", "complete", "landed", "live", "accepted"].some(x => state.includes(x))) return "ok"; if (["stale", "invalid", "failed", "error", "diverged", "expired", "rejected"].some(x => state.includes(x))) return "bad"; if (["waiting", "review", "implement", "planning", "checking", "active", "uncertain"].some(x => state.includes(x))) return "warn"; return ""; }
function streamState(state, detail = "") { $("stream-state").textContent = state; $("stream-dot").className = `stream-dot ${state === "LIVE" ? "live" : state === "OFFLINE" ? "offline" : "waiting"}`; if (detail) $("observed-at").textContent = detail; }
function notice(message = "", bad = false) { $("notice").hidden = !message; $("notice").textContent = message; $("notice").className = `notice ${bad ? "bad" : ""}`; }
function projectSessions() { return (workspaceState.sessions || []).filter(item => item.project_id === selectedProject); }
function currentProject() { return (workspaceState.projects || []).find(item => item.id === selectedProject) || null; }
function currentSession() { return activeSession?.id === selectedSession ? activeSession : projectSessions().find(item => item.id === selectedSession) || null; }

function renderProjects() {
  const projects = workspaceState.projects || []; if (!projects.some(item => item.id === selectedProject)) selectedProject = projects[0]?.id || "";
  $("projects-empty").hidden = projects.length !== 0;
  $("projects").innerHTML = projects.map(item => `<button type="button" class="nav-item ${item.id === selectedProject ? "active" : ""} ${item.available && item.initialized ? "" : "unavailable"}" data-project="${esc(item.id)}"><strong>${esc(item.name)}</strong><span>${esc(item.available && item.initialized ? `${item.sessions} sessions` : "folder unavailable")}</span></button>`).join("");
  $("projects").querySelectorAll("[data-project]").forEach(button => button.addEventListener("click", () => selectProject(button.dataset.project)));
}
function renderSessions() {
  const sessions = projectSessions(); if (!sessions.some(item => item.id === selectedSession)) selectedSession = sessions[0]?.id || "";
  $("sessions-empty").hidden = sessions.length !== 0;
  $("sessions").innerHTML = sessions.map(item => `<button type="button" class="nav-item ${item.id === selectedSession ? "active" : ""}" data-session="${esc(item.id)}"><strong>${esc(item.theme)}${item.live ? ' <em class="live" title="a console holds this session">live</em>' : ''}</strong><span>${esc(item.mode)} · ${item.message_count ?? (item.messages || []).length} messages</span></button>`).join("");
  $("sessions").querySelectorAll("[data-session]").forEach(button => button.addEventListener("click", () => selectSession(button.dataset.session)));
}
function renderConversation() {
  const project = currentProject(); const session = currentSession(); $("project-path").textContent = project?.path || "Choose a project";
  $("conversation-empty").hidden = Boolean(session); $("conversation").hidden = !session;
  if (!session) { $("session-title").textContent = project ? "Open a session" : "Initialize a repository"; $("session-meta").textContent = project ? "Sessions keep one theme grounded in one folder." : "Use invariant project add <folder> in a terminal."; return; }
  $("session-title").textContent = session.theme; $("session-meta").textContent = `${session.id} · ${session.provider || "provider on first turn"} · updated ${session.updated_at || "now"}`;
  $("composer-scope").textContent = session.mode === "change" ? "Coordinator may start a managed change" : "Read-only repository conversation";
  $("prompt").placeholder = session.mode === "change" ? "Ask, or request a managed change…" : "Ask about this project…";
  const messages = session.messages || [];
  $("messages").innerHTML = messages.length ? messages.map(message => `<article class="message ${esc(message.role)} ${message.state === "failed" ? "failed" : ""}"><span class="role">${esc(message.role)}</span><p class="content">${esc(message.content)}</p></article>`).join("") : `<article class="message system"><span class="role">Ready</span><p class="content">Start this theme with a question or a concrete request.</p></article>`;
}
function renderRepository() {
  const repo = repositorySnapshot?.repository || {};
  $("repository-facts").innerHTML = repo.name ? [["Branch", repo.branch || "detached"], ["Head", short(repo.head)], ["State", repo.state || "unknown"], ["Authority", repo.authority || "—"]].map(([name, value]) => `<dt>${esc(name)}</dt><dd>${esc(value)}</dd>`).join("") : "";
  const tasks = repositorySnapshot?.tasks || []; $("activity-count").textContent = `${tasks.length} active`;
  $("tasks").innerHTML = tasks.length ? tasks.map(item => { const state = item.freshness || item.stage; return `<article class="task ${tone(state) === "bad" ? "bad" : tone(state) === "warn" ? "attention" : ""}"><div class="task-head"><strong>${esc(item.id)}</strong><span class="tag ${tone(state)}">${esc(item.stage)}</span></div><div class="task-meta"><span>${esc(item.kind)}</span><span>${esc(item.freshness)}</span><span>target ${esc(item.target || "—")}</span><span>${esc(item.pending_actions)} pending</span></div></article>`; }).join("") : `<p class="activity-empty">No active changes. Repository mechanics are ready.</p>`;
  const diagnostics = repositorySnapshot?.diagnostics || []; if (diagnostics.length) notice(diagnostics.join(" · "), true);
}
function renderAll() { renderProjects(); renderSessions(); renderConversation(); renderRepository(); }

async function loadState({quiet = false} = {}) {
  try { const response = await fetch("/host/v1/state", {cache: "no-store"}); if (!response.ok) throw new Error(`HTTP ${response.status}`); const next = await response.json(); workspaceState = next; token = next.csrf_token || token; renderAll(); const summary = (next.sessions || []).find(item => item.id === selectedSession); const transcriptChanged = summary && summary.updated_at !== activeSession?.updated_at; if (!summary) { activeSession = null; renderConversation(); } if (summary && (!activeSession || transcriptChanged)) await loadSession(); if (!quiet || selectedProject !== connectedProject) connectProject(); }
  catch (error) { streamState("OFFLINE", `workspace unavailable · ${error.message}`); }
}
async function loadSession() {
  if (!selectedSession) { activeSession = null; renderConversation(); return; }
  try { const response = await fetch(`/host/v1/sessions/${encodeURIComponent(selectedSession)}`, {cache: "no-store"}); const value = await response.json(); if (!response.ok) throw new Error(value.message || `HTTP ${response.status}`); activeSession = value.session; renderConversation(); }
  catch (error) { activeSession = null; notice(error.message, true); }
}
async function loadProjectSnapshot() {
  repositorySnapshot = null; if (!selectedProject) { renderRepository(); return; }
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
function selectProject(identifier) { selectedProject = identifier; selectedSession = projectSessions()[0]?.id || ""; activeSession = null; localStorage.setItem("invariant.project", selectedProject); localStorage.setItem("invariant.session", selectedSession); notice(); renderAll(); loadSession(); connectProject(); }
function selectSession(identifier) { selectedSession = identifier; activeSession = null; localStorage.setItem("invariant.session", selectedSession); notice(); renderSessions(); renderConversation(); loadSession().then(() => $("prompt").focus()); }
async function post(path, body) { const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json", "X-Invariant-Token": token}, body: JSON.stringify(body)}); const value = await response.json(); if (!response.ok) throw new Error(value.message || `HTTP ${response.status}`); return value; }

$("new-session-toggle").addEventListener("click", () => { if (!selectedProject) { notice("Register and select a project before creating a session.", true); return; } $("new-session-form").hidden = !$("new-session-form").hidden; if (!$("new-session-form").hidden) $("session-theme").focus(); });
$("new-session-form").addEventListener("submit", async event => {
  event.preventDefault(); const button = event.currentTarget.querySelector("button"); button.disabled = true;
  try { const value = await post(`/host/v1/projects/${encodeURIComponent(selectedProject)}/sessions`, {theme: $("session-theme").value, mode: $("session-mode").value}); selectedSession = value.session.id; activeSession = value.session; $("session-theme").value = ""; $("new-session-form").hidden = true; await loadState({quiet: true}); localStorage.setItem("invariant.session", selectedSession); renderAll(); $("prompt").focus(); }
  catch (error) { notice(error.message, true); } finally { button.disabled = false; }
});
$("composer").addEventListener("submit", async event => {
  event.preventDefault(); const session = currentSession(); const message = $("prompt").value.trim(); if (!session || !message) return;
  $("send").disabled = true; $("prompt").disabled = true; notice("The agent is working in this project…"); session.messages = [...(session.messages || []), {role: "user", content: message, state: "complete"}]; $("prompt").value = ""; renderConversation();
  try { const value = await post(`/host/v1/sessions/${encodeURIComponent(session.id)}/turns`, {message}); activeSession = value.session; await loadState({quiet: true}); notice(); renderAll(); }
  catch (error) { notice(error.message, true); await loadState({quiet: true}); }
  finally { $("send").disabled = false; $("prompt").disabled = false; $("prompt").focus(); }
});
$("prompt").addEventListener("keydown", event => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") $("composer").requestSubmit(); });
loadState(); window.setInterval(() => loadState({quiet: true}), 3000);
"""
