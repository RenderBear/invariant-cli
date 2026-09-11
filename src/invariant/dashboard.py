from __future__ import annotations


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Invariant · Repository observer</title>
  <link rel="stylesheet" href="/assets/app.css">
</head>
<body>
  <main>
    <header class="masthead">
      <div class="identity">
        <pre class="wordmark" aria-label="Invariant">█ █▄ █ █ █ ▄▀▄ █▀▄ █ ▄▀▄ █▄ █ ▀█▀
█ █ ▀█ ▀▄▀ █▀█ █▀▄ █ █▀█ █ ▀█  █ </pre>
        <p>Repository observer · read only</p>
      </div>
      <div class="stream" aria-live="polite">
        <span id="stream-dot" class="stream-dot waiting"></span>
        <span id="stream-state">CONNECTING</span>
        <span class="muted" id="observed-at">waiting for snapshot</span>
      </div>
    </header>

    <section class="repository" aria-labelledby="repository-title">
      <div>
        <p class="eyebrow">Repository</p>
        <h1 id="repository-title">Loading…</h1>
        <p class="muted path" id="repository-path"></p>
      </div>
      <dl class="repository-facts" id="repository-facts"></dl>
    </section>

    <section class="counters" id="counters" aria-label="Repository summary"></section>

    <section id="diagnostics" class="diagnostics" aria-live="polite" hidden></section>

    <section class="block" aria-labelledby="processes-title">
      <div class="section-head">
        <div><p class="eyebrow">Presence</p><h2 id="processes-title">Running processes</h2></div>
        <p class="muted">Heartbeat presence is advisory; receipts and Git remain authoritative.</p>
      </div>
      <div class="table-wrap" id="processes"></div>
    </section>

    <section class="block" aria-labelledby="tasks-title">
      <div class="section-head">
        <div><p class="eyebrow">Lifecycle</p><h2 id="tasks-title">Active changes</h2></div>
        <p class="muted" id="task-caption"></p>
      </div>
      <div class="task-list" id="tasks"></div>
    </section>

    <section class="block" aria-labelledby="coordination-title">
      <div class="section-head">
        <div><p class="eyebrow">Concurrency</p><h2 id="coordination-title">Plans and leases</h2></div>
        <p class="muted">Temporary ownership against an exact integration ground.</p>
      </div>
      <div class="split">
        <div><h3>Plans</h3><div id="plans"></div></div>
        <div><h3>Leases</h3><div id="leases" class="table-wrap"></div></div>
      </div>
    </section>

    <section class="block" aria-labelledby="governance-title">
      <div class="section-head">
        <div><p class="eyebrow">Accepted meaning</p><h2 id="governance-title">Governance</h2></div>
        <p class="muted" id="governance-caption"></p>
      </div>
      <div class="record-list" id="governance"></div>
    </section>

    <section class="block" aria-labelledby="evidence-title">
      <div class="section-head">
        <div><p class="eyebrow">Causal record</p><h2 id="evidence-title">Evidence run-through</h2></div>
        <p class="muted">Newest first · exact trees and grounds remain visible.</p>
      </div>
      <div class="evidence-list" id="evidence"></div>
    </section>

    <section class="block" aria-labelledby="history-title">
      <div class="section-head">
        <div><p class="eyebrow">Local archive</p><h2 id="history-title">Recent landings</h2></div>
        <p class="muted">Completed task summaries retained in ignored runtime history.</p>
      </div>
      <div class="table-wrap" id="history"></div>
    </section>

    <footer>
      <span>HTTP snapshot + Server-Sent Events</span>
      <span id="revision">revision —</span>
      <span>No chat · no write endpoints</span>
    </footer>
  </main>
  <script src="/assets/app.js" defer></script>
</body>
</html>
"""


CSS = """:root {
  color-scheme: light;
  --ink: #171717;
  --muted: #626262;
  --line: #b8b8b8;
  --soft: #eeeeec;
  --paper: #ffffff;
  --accent: #007f92;
  --ok: #237a3b;
  --warn: #9a6700;
  --bad: #b42318;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}

* { box-sizing: border-box; }
html { background: var(--paper); color: var(--ink); font-family: var(--sans); }
body { margin: 0; }
main { width: min(1180px, calc(100% - 40px)); margin: 0 auto; padding: 34px 0 48px; }

.masthead {
  align-items: flex-end;
  border-bottom: 2px solid var(--ink);
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 20px;
}
.wordmark {
  color: var(--accent);
  font: 700 14px/1.05 var(--mono);
  letter-spacing: 0;
  margin: 0;
  white-space: pre;
}
.identity p, .stream, .eyebrow, footer, th, dt, .tag, .stage, .meta {
  font-family: var(--mono);
}
.identity p { color: var(--muted); font-size: 11px; margin: 8px 0 0; text-transform: uppercase; }
.stream { align-items: center; display: flex; flex-wrap: wrap; font-size: 11px; gap: 8px; justify-content: flex-end; }
.stream-dot { border: 1px solid currentColor; display: inline-block; height: 9px; width: 9px; }
.stream-dot.live { background: var(--ok); color: var(--ok); }
.stream-dot.waiting { background: var(--warn); color: var(--warn); }
.stream-dot.offline { background: var(--bad); color: var(--bad); }

.repository { align-items: end; display: flex; justify-content: space-between; gap: 28px; padding: 34px 0 30px; }
.eyebrow { color: var(--muted); font-size: 10px; letter-spacing: .08em; margin: 0 0 7px; text-transform: uppercase; }
h1 { font-size: clamp(27px, 4vw, 42px); letter-spacing: -.035em; line-height: 1.05; margin: 0; }
h2 { font-size: 22px; letter-spacing: -.02em; margin: 0; }
h3 { font: 700 12px/1.3 var(--mono); letter-spacing: .04em; margin: 0 0 12px; text-transform: uppercase; }
.muted { color: var(--muted); }
.path { font: 11px/1.5 var(--mono); margin: 10px 0 0; overflow-wrap: anywhere; }
.repository-facts { display: grid; gap: 7px 18px; grid-template-columns: auto auto; margin: 0; min-width: 310px; }
dt { color: var(--muted); font-size: 10px; text-transform: uppercase; }
dd { font: 12px/1.3 var(--mono); margin: 0; text-align: right; }

.counters { border: 1px solid var(--ink); display: grid; grid-template-columns: repeat(4, 1fr); margin-bottom: 62px; }
.counter { min-height: 94px; padding: 17px 18px; }
.counter + .counter { border-left: 1px solid var(--line); }
.counter strong { display: block; font: 700 28px/1 var(--mono); margin-top: 13px; }
.counter span { color: var(--muted); font: 10px var(--mono); letter-spacing: .06em; text-transform: uppercase; }
.diagnostics { border: 1px solid var(--bad); color: var(--bad); font: 11px/1.55 var(--mono); margin: -42px 0 42px; padding: 13px 16px; }
.diagnostics strong { display: block; margin-bottom: 4px; text-transform: uppercase; }
.diagnostics p { margin: 0; overflow-wrap: anywhere; }

.block { border-top: 1px solid var(--ink); padding: 23px 0 58px; }
.section-head { align-items: start; display: flex; gap: 32px; justify-content: space-between; margin-bottom: 22px; }
.section-head > p { font-size: 13px; line-height: 1.5; margin: 0; max-width: 500px; text-align: right; }
.split { display: grid; gap: 36px; grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); }

.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; font-size: 13px; width: 100%; }
th { background: var(--soft); border-bottom: 1px solid var(--ink); font-size: 10px; letter-spacing: .04em; padding: 10px 12px; text-align: left; text-transform: uppercase; }
td { border-bottom: 1px solid var(--line); padding: 11px 12px; vertical-align: top; }
td.mono { font-family: var(--mono); font-size: 11px; }
.empty { border: 1px dashed var(--line); color: var(--muted); font-size: 13px; margin: 0; padding: 20px; }

.task-list, .record-list, .evidence-list, .plan-list { display: grid; gap: 12px; }
.task, .plan, .record, .evidence-item { border: 1px solid var(--line); padding: 16px 18px; }
.task.attention, .plan.attention, .evidence-item.attention { border-color: var(--warn); }
.task.bad, .plan.bad, .record.bad, .evidence-item.bad { border-color: var(--bad); }
.unit-head { align-items: baseline; display: flex; gap: 14px; justify-content: space-between; }
.unit-head strong { font-size: 14px; overflow-wrap: anywhere; }
.tag { border: 1px solid currentColor; color: var(--muted); font-size: 9px; letter-spacing: .04em; padding: 3px 5px; text-transform: uppercase; white-space: nowrap; }
.tag.ok { color: var(--ok); }
.tag.warn { color: var(--warn); }
.tag.bad { color: var(--bad); }
.meta { color: var(--muted); display: flex; flex-wrap: wrap; font-size: 10px; gap: 6px 16px; margin-top: 11px; overflow-wrap: anywhere; }
.summary { font-size: 13px; line-height: 1.5; margin: 11px 0 0; }

.stages { display: grid; grid-template-columns: repeat(5, 1fr); margin-top: 16px; }
.stage { border-top: 2px solid var(--line); color: var(--muted); font-size: 9px; padding-top: 7px; text-transform: uppercase; }
.stage.done { border-color: var(--ok); color: var(--ok); }
.stage.current { border-color: var(--warn); color: var(--warn); font-weight: 700; }
.stage.bad { border-color: var(--bad); color: var(--bad); }

.plan-units { border-top: 1px solid var(--line); margin-top: 13px; padding-top: 8px; }
.plan-unit { display: grid; font: 10px/1.45 var(--mono); gap: 9px; grid-template-columns: minmax(100px, 1fr) 90px 1fr; padding: 5px 0; }
.plan-unit + .plan-unit { border-top: 1px dotted var(--line); }
.record-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.record p { margin: 9px 0 0; }

.evidence-item { display: grid; gap: 16px; grid-template-columns: minmax(150px, .7fr) minmax(260px, 1.3fr); }
.evidence-item .summary { margin: 0; }
.causal { border-left: 1px solid var(--line); font: 10px/1.7 var(--mono); overflow-wrap: anywhere; padding-left: 16px; }
.causal b { color: var(--muted); display: inline-block; font-weight: 400; min-width: 62px; text-transform: uppercase; }

.ok-text { color: var(--ok); }
.warn-text { color: var(--warn); }
.bad-text { color: var(--bad); }
footer { border-top: 2px solid var(--ink); color: var(--muted); display: flex; flex-wrap: wrap; font-size: 9px; gap: 10px 24px; justify-content: space-between; padding-top: 15px; text-transform: uppercase; }

@media (max-width: 760px) {
  main { width: min(100% - 28px, 1180px); padding-top: 22px; }
  .masthead, .repository, .section-head { align-items: start; flex-direction: column; }
  .stream { justify-content: flex-start; }
  .repository-facts { min-width: 0; width: 100%; }
  .counters { grid-template-columns: repeat(2, 1fr); }
  .counter:nth-child(3) { border-left: 0; border-top: 1px solid var(--line); }
  .counter:nth-child(4) { border-top: 1px solid var(--line); }
  .section-head > p { text-align: left; }
  .split, .record-list { grid-template-columns: 1fr; }
  .evidence-item { grid-template-columns: 1fr; }
  .causal { border-left: 0; border-top: 1px solid var(--line); padding: 12px 0 0; }
}

@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
"""


JS = r"""const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const short = (value, size = 10) => value ? String(value).slice(0, size) : "—";
const list = (value) => Array.isArray(value) && value.length ? value.join(", ") : "—";

function tone(value) {
  const state = String(value || "").toLowerCase();
  if (["fresh", "valid", "passed", "complete", "completed", "landed", "live", "ready", "accepted"].some(x => state.includes(x))) return "ok";
  if (["stale", "invalid", "failed", "error", "diverged", "expired", "rejected"].some(x => state.includes(x))) return "bad";
  if (["waiting", "review", "implement", "planning", "checking", "attention", "active", "uncertain"].some(x => state.includes(x))) return "warn";
  return "";
}

function tag(value) {
  return `<span class="tag ${tone(value)}">${esc(value || "unknown")}</span>`;
}

function empty(message) {
  return `<p class="empty">${esc(message)}</p>`;
}

function facts(values) {
  return Object.entries(values).map(([name, value]) => `<dt>${esc(name)}</dt><dd>${esc(value)}</dd>`).join("");
}

function table(headers, rows) {
  if (!rows.length) return empty("Nothing active.");
  return `<table><thead><tr>${headers.map(x => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

function renderProcesses(processes) {
  const rows = processes.map(item => `<tr>
    <td class="mono">${esc(item.pid)}</td>
    <td>${esc(item.command)}</td>
    <td>${tag(item.state)}</td>
    <td class="mono">${esc(item.task || "—")}</td>
    <td class="mono">${esc(item.started || "—")}</td>
  </tr>`);
  $("processes").innerHTML = table(["PID", "Command", "Presence", "Task", "Started"], rows);
}

const lifecycle = ["brief", "work", "evidence", "review", "land"];
function stageIndex(stage) {
  const value = String(stage || "");
  if (value.includes("brief")) return 0;
  if (value.includes("implement") || value.includes("branch")) return 1;
  if (value.includes("review")) return 3;
  if (value.includes("landing") || value.includes("cleanup") || value.includes("complete")) return 4;
  return 0;
}

function renderTasks(tasks) {
  $("task-caption").textContent = tasks.length ? `${tasks.length} retained lifecycle ${tasks.length === 1 ? "receipt" : "receipts"}.` : "No unfinished changes.";
  if (!tasks.length) { $("tasks").innerHTML = empty("No active changes. The repository is ready for a managed request."); return; }
  $("tasks").innerHTML = tasks.map(item => {
    const current = stageIndex(item.stage);
    const bad = item.freshness === "stale" || item.freshness === "diverged" || item.stage === "cleanup-required";
    const stages = lifecycle.map((name, index) => `<span class="stage ${index < current ? "done" : index === current ? (bad ? "bad" : "current") : ""}">${name}</span>`).join("");
    const problems = Array.isArray(item.stale_reasons) && item.stale_reasons.length ? `<p class="summary bad-text">${esc(item.stale_reasons.join(" · "))}</p>` : "";
    return `<article class="task ${bad ? "bad" : "attention"}">
      <div class="unit-head"><strong>${esc(item.id)}</strong><div>${tag(item.stage)} ${tag(item.freshness)}</div></div>
      <div class="meta"><span>${esc(item.kind)}</span><span>target ${esc(item.target || "—")}</span><span>base ${esc(short(item.base))}</span><span>boundary ${esc(item.boundary || "unresolved")}</span><span>${esc(item.pending_actions)} pending actions</span></div>
      ${problems}<div class="stages">${stages}</div>
    </article>`;
  }).join("");
}

function renderPlans(plans) {
  if (!plans.length) { $("plans").innerHTML = empty("No coordination plans."); return; }
  $("plans").innerHTML = `<div class="plan-list">${plans.map(plan => `<article class="plan ${plan.valid ? "" : "bad"}">
    <div class="unit-head"><strong>${esc(plan.id)}</strong>${tag(plan.valid ? "valid" : "invalid")}</div>
    <p class="summary">${esc(plan.summary || "No plan summary.")}</p>
    ${plan.diagnostics?.length ? `<p class="summary bad-text">${esc(plan.diagnostics.join(" · "))}</p>` : ""}
    <div class="plan-units">${(plan.units || []).map(unit => `<div class="plan-unit"><span>${esc(unit.id)}</span><span class="${tone(unit.state)}-text">${esc(unit.state)}</span><span>${esc(list(unit.dependencies))}</span></div>`).join("")}</div>
  </article>`).join("")}</div>`;
}

function renderLeases(leases) {
  const rows = leases.map(item => `<tr>
    <td class="mono">${esc(item.unit)}</td><td>${tag(item.state)}</td>
    <td class="mono">${esc(item.owner || "—")}</td><td class="mono">${esc(item.expires || "—")}</td>
  </tr>`);
  $("leases").innerHTML = table(["Unit", "State", "Owner", "Expires"], rows);
}

function renderGovernance(governance) {
  const records = governance.records || [];
  $("governance-caption").textContent = `${records.length} accepted record ${records.length === 1 ? "projection" : "projections"}; repository state is ${governance.state || "unknown"}.`;
  if (!records.length) { $("governance").innerHTML = empty("No accepted governance records."); return; }
  $("governance").innerHTML = records.map(item => `<article class="record ${tone(item.status) === "bad" ? "bad" : ""}">
    <div class="unit-head"><strong>${esc(item.kind)}:${esc(item.id)}</strong>${tag(item.status || "active")}</div>
    <p class="summary">${esc(item.summary || item.document || "Accepted repository meaning.")}</p>
    <div class="meta"><span>${esc(item.authority || "authority unknown")}</span><span>${esc(item.path)}</span></div>
  </article>`).join("");
}

function renderEvidence(evidence) {
  if (!evidence.length) { $("evidence").innerHTML = empty("No captured evidence yet."); return; }
  $("evidence").innerHTML = evidence.map(item => {
    const state = item.freshness || item.status || "recorded";
    const causal = [
      ["Task", item.task], ["Ground", short(item.ground || item.base)], ["Tree", short(item.tree)],
      ["Locator", item.locator], ["Captured", item.captured_at], ["Duration", item.duration_ms != null ? `${item.duration_ms} ms` : ""]
    ].filter(([, value]) => value).map(([name, value]) => `<div><b>${esc(name)}</b>${esc(value)}</div>`).join("");
    const displayId = String(item.id || "").replace(`${item.kind}:`, "");
    return `<article class="evidence-item ${tone(state) === "bad" ? "bad" : tone(state) === "warn" ? "attention" : ""}">
      <div><div class="unit-head"><strong>${esc(item.kind)} · ${esc(displayId)}</strong>${tag(state)}</div><p class="summary">${esc(item.summary || item.command || "Captured exact-tree evidence.")}</p></div>
      <div class="causal">${causal || "Recorded without additional causal display fields."}</div>
    </article>`;
  }).join("");
}

function renderHistory(history) {
  const rows = history.map(item => `<tr>
    <td>${esc(item.task)}</td><td>${tag(item.status || "completed")}</td>
    <td class="mono">${esc(short(item.commit))}</td><td>${esc(item.boundary || "—")}</td>
  </tr>`);
  $("history").innerHTML = table(["Task", "Status", "Landing", "Boundary"], rows);
}

function render(snapshot) {
  const repo = snapshot.repository || {};
  $("repository-title").textContent = repo.name || "Repository";
  $("repository-path").textContent = repo.path || "";
  $("repository-facts").innerHTML = facts({
    Branch: repo.branch || "detached", Integration: repo.integration_branch || "—",
    Head: short(repo.head), State: repo.state || "unknown", Authority: repo.authority || "—", Execution: repo.execution || "—"
  });
  const counters = [
    ["Running processes", (snapshot.processes || []).filter(x => x.state === "running").length],
    ["Active changes", (snapshot.tasks || []).length],
    ["Governance records", snapshot.governance?.records?.length || 0],
    ["Evidence entries", (snapshot.evidence || []).length]
  ];
  $("counters").innerHTML = counters.map(([label, value]) => `<div class="counter"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
  const diagnostics = Array.isArray(snapshot.diagnostics) ? snapshot.diagnostics : [];
  $("diagnostics").hidden = diagnostics.length === 0;
  $("diagnostics").innerHTML = diagnostics.length
    ? `<strong>State diagnostics</strong>${diagnostics.map(item => `<p>${esc(item)}</p>`).join("")}`
    : "";
  renderProcesses(snapshot.processes || []);
  renderTasks(snapshot.tasks || []);
  renderPlans(snapshot.plans || []);
  renderLeases(snapshot.leases || []);
  renderGovernance(snapshot.governance || {});
  renderEvidence(snapshot.evidence || []);
  renderHistory(snapshot.history || []);
  $("observed-at").textContent = snapshot.observed_at ? `observed ${snapshot.observed_at}` : "snapshot received";
  $("revision").textContent = `revision ${short(snapshot.revision, 12)}`;
}

function streamState(state, detail) {
  $("stream-state").textContent = state;
  $("stream-dot").className = `stream-dot ${state === "LIVE" ? "live" : state === "OFFLINE" ? "offline" : "waiting"}`;
  if (detail) $("observed-at").textContent = detail;
}

async function initial() {
  try {
    const response = await fetch("/api/v1/snapshot", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    streamState("OFFLINE", `snapshot failed · ${error.message}`);
  }
}

function connect() {
  const events = new EventSource("/api/v1/events");
  events.addEventListener("open", () => streamState("LIVE"));
  events.addEventListener("snapshot", event => {
    try { render(JSON.parse(event.data)); streamState("LIVE"); }
    catch (error) { streamState("RECONNECTING", `invalid event · ${error.message}`); }
  });
  events.addEventListener("error", () => streamState("RECONNECTING", "waiting for the local event stream"));
}

initial();
connect();
"""
