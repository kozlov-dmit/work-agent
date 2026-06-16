"""Web chat server: a browser UI that submits tasks over a WebSocket.

Each WebSocket connection is one chat session with its own agent and history.
Agent turns run in a thread (the SDK calls and tools are blocking); events are
streamed back to the browser live via a thread-safe asyncio queue.
"""

from __future__ import annotations

import asyncio
import json

from ..agent import AgentEvents
from ..config import Config
from ..permissions import auto_allow
from ..runtime import build_agent

_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>work-agent</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; display: flex;
         flex-direction: column; height: 100vh; }
  header { padding: .6rem 1rem; border-bottom: 1px solid #8884; font-weight: 600; }
  #log { flex: 1; overflow-y: auto; padding: 1rem; display: flex;
         flex-direction: column; gap: .5rem; }
  .msg { padding: .5rem .75rem; border-radius: .5rem; max-width: 75%;
         white-space: pre-wrap; word-wrap: break-word; }
  .user { align-self: flex-end; background: #2563eb; color: #fff; }
  .agent { align-self: flex-start; background: #8882; }
  .tool { align-self: flex-start; font-family: monospace; font-size: .85em;
          opacity: .8; }
  .err { color: #dc2626; }
  form { display: flex; gap: .5rem; padding: .75rem; border-top: 1px solid #8884; }
  input { flex: 1; padding: .6rem; border-radius: .5rem; border: 1px solid #8886; }
  button { padding: .6rem 1rem; border-radius: .5rem; border: 0;
           background: #2563eb; color: #fff; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
</style>
</head>
<body>
<header>work-agent — chat &nbsp;·&nbsp; <a href="/dashboard">dashboard</a></header>
<div id="log"></div>
<form id="form">
  <input id="input" autocomplete="off" placeholder="Describe a task…" />
  <button id="send" type="submit">Send</button>
</form>
<script>
  const log = document.getElementById("log");
  const form = document.getElementById("form");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");

  function add(cls, text) {
    const el = document.createElement("div");
    el.className = "msg " + cls;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "text") add("agent", m.text);
    else if (m.type === "tool_call") add("tool", "→ " + m.name + " " + JSON.stringify(m.arguments));
    else if (m.type === "tool_result") add("tool" + (m.is_error ? " err" : ""), (m.is_error ? "✗ " : "✓ ") + m.name);
    else if (m.type === "denied") add("tool err", "denied: " + m.name);
    else if (m.type === "compaction") add("tool", "🗜 compacted history (" + m.messages + " messages)");
    else if (m.type === "done") { send.disabled = false; input.disabled = false; input.focus(); }
    else if (m.type === "error") { add("agent err", m.text); send.disabled = false; input.disabled = false; }
  };
  ws.onclose = () => add("agent err", "[disconnected]");

  form.onsubmit = (e) => {
    e.preventDefault();
    const task = input.value.trim();
    if (!task || ws.readyState !== 1) return;
    add("user", task);
    ws.send(JSON.stringify({ task }));
    input.value = "";
    send.disabled = true;
    input.disabled = true;
  };
</script>
</body>
</html>
"""


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>work-agent — dashboard</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; }
  header { padding: .6rem 1rem; border-bottom: 1px solid #8884; font-weight: 600; }
  nav { display: flex; gap: .5rem; padding: .5rem 1rem; border-bottom: 1px solid #8884; }
  nav button { padding: .4rem .8rem; border: 1px solid #8886; border-radius: .5rem;
               background: transparent; cursor: pointer; }
  nav button.active { background: #2563eb; color: #fff; border-color: #2563eb; }
  main { padding: 1rem; max-width: 880px; }
  section { display: none; }
  section.active { display: block; }
  .cards { display: flex; flex-wrap: wrap; gap: .75rem; }
  .card { flex: 1 1 140px; border: 1px solid #8884; border-radius: .6rem; padding: .75rem; }
  .card .v { font-size: 1.5rem; font-weight: 700; }
  .card .l { opacity: .7; font-size: .8rem; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: .4rem; border-bottom: 1px solid #8883; font-size: .9rem; }
  label { display: block; margin: .5rem 0 .15rem; font-size: .85rem; opacity: .8; }
  input, select, textarea { width: 100%; padding: .4rem; border: 1px solid #8886;
                            border-radius: .4rem; box-sizing: border-box; font: inherit; }
  textarea { min-height: 6rem; }
  button.go { margin-top: .8rem; padding: .5rem 1rem; border: 0; border-radius: .5rem;
              background: #2563eb; color: #fff; cursor: pointer; }
  .row { display: flex; gap: .5rem; } .row > * { flex: 1; }
  .muted { opacity: .65; font-size: .85rem; }
  .ok { color: #16a34a; } .bad { color: #dc2626; }
</style>
</head>
<body>
<header>work-agent — dashboard &nbsp;·&nbsp; <a href="/">chat</a></header>
<nav>
  <button data-tab="metrics" class="active">Metrics</button>
  <button data-tab="tasks">Scheduled tasks</button>
  <button data-tab="config">Config</button>
</nav>
<main>
  <section id="metrics" class="active">
    <div class="cards" id="sys"></div>
    <h3>Tokens & reliability</h3>
    <div class="cards" id="usage"></div>
    <p class="muted" id="uptime"></p>
  </section>

  <section id="tasks">
    <table><thead><tr><th>id</th><th>cron</th><th>deliver</th><th>next</th>
      <th>task</th><th></th></tr></thead><tbody id="tasks-body"></tbody></table>
    <h3>Add task</h3>
    <div class="row">
      <div><label>cron</label><input id="t-cron" placeholder="0 9 * * *" /></div>
      <div><label>timezone (optional)</label><input id="t-tz" placeholder="Europe/Moscow" /></div>
    </div>
    <label>task</label><input id="t-task" placeholder="send a news digest" />
    <button class="go" id="t-add">Add</button>
    <p class="muted">Dashboard-created tasks deliver to a log file under
      /workspace/.work-agent/schedule-output/.</p>
  </section>

  <section id="config">
    <h3>Models per purpose</h3>
    <div id="profiles"></div>
    <label>Default profile</label><select id="c-default"></select>
    <label>System prompt addendum (appended to every turn)</label>
    <textarea id="c-extra" placeholder="Extra instructions..."></textarea>
    <div class="row">
      <div><label>Effort</label>
        <select id="c-effort"><option>low</option><option>medium</option>
          <option>high</option><option>xhigh</option><option>max</option></select></div>
      <div><label>Permission default</label>
        <select id="c-perm"><option>allow</option><option>ask</option><option>deny</option></select></div>
      <div><label>Max iterations</label><input id="c-maxit" type="number" /></div>
    </div>
    <button class="go" id="c-save">Save config</button>
    <p class="muted" id="c-status"></p>
  </section>
</main>
<script>
  const $ = (id) => document.getElementById(id);
  document.querySelectorAll("nav button").forEach((b) => b.onclick = () => {
    document.querySelectorAll("nav button").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll("section").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); $(b.dataset.tab).classList.add("active");
  });
  const card = (v, l) => `<div class="card"><div class="v">${v}</div><div class="l">${l}</div></div>`;

  async function loadMetrics() {
    const m = await (await fetch("/api/metrics")).json();
    const s = m.system || {};
    $("sys").innerHTML = s.available
      ? card(s.cpu_percent + "%", "CPU") + card(s.memory_percent + "%", "Memory")
        + card(s.memory_used_mb + " / " + s.memory_total_mb + " MB", "RAM used")
        + card(s.net_sent_mb + " / " + s.net_recv_mb + " MB", "Net sent / recv")
      : card("n/a", "System metrics (install psutil)");
    const rel = (m.llm.reliability * 100).toFixed(1);
    $("usage").innerHTML = card(m.tokens.total, "Tokens total")
      + card(m.tokens.input + " / " + m.tokens.output, "Input / output")
      + card(rel + "%", "LLM reliability")
      + card(m.llm.requests, "LLM requests")
      + card(m.llm.failures, "Failures")
      + card(m.tools.calls + " / " + m.tools.errors, "Tool calls / errors");
    $("uptime").textContent = "uptime: " + m.uptime_seconds + "s · refusals: " + m.llm.refusals;
  }

  async function loadTasks() {
    const d = await (await fetch("/api/schedules")).json();
    $("tasks-body").innerHTML = (d.tasks || []).map((t) => `<tr>
      <td>${t.id}</td><td>${t.cron}</td><td>${(t.delivery||{}).type||""}</td>
      <td>${t.next_run||""}</td><td>${(t.task||"").slice(0,40)}</td>
      <td><button onclick="toggle('${t.id}','${t.enabled?"disable":"enable"}')">${t.enabled?"disable":"enable"}</button>
          <button onclick="del('${t.id}')">delete</button></td></tr>`).join("");
  }
  window.toggle = async (id, action) => { await fetch(`/api/schedules/${id}/${action}`, {method:"POST"}); loadTasks(); };
  window.del = async (id) => { await fetch(`/api/schedules/${id}`, {method:"DELETE"}); loadTasks(); };
  $("t-add").onclick = async () => {
    const body = { cron: $("t-cron").value, task: $("t-task").value, timezone: $("t-tz").value || null };
    const r = await (await fetch("/api/schedules", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)})).json();
    if (r.status !== "ok") alert(r.message || "error"); else { $("t-cron").value=$("t-task").value=$("t-tz").value=""; loadTasks(); }
  };

  let CFG = null, ROLES = [], PROVIDERS = [];
  async function loadConfig() {
    const d = await (await fetch("/api/config")).json();
    CFG = d.config; ROLES = d.roles; PROVIDERS = d.providers;
    $("profiles").innerHTML = ROLES.map((role) => {
      const p = (CFG.profiles && CFG.profiles[role]) || {};
      const opts = PROVIDERS.map((pr) => `<option ${pr===(p.provider||"")?"selected":""}>${pr}</option>`).join("");
      return `<div class="row" style="margin-bottom:.4rem"><div><label>${role} · provider</label>
        <select data-role="${role}" data-k="provider"><option value=""></option>${opts}</select></div>
        <div><label>model</label><input data-role="${role}" data-k="model" value="${p.model||""}" /></div>
        <div><label>effort</label><input data-role="${role}" data-k="effort" value="${p.effort||""}" /></div></div>`;
    }).join("");
    $("c-default").innerHTML = ROLES.map((r) => `<option ${r===CFG.default_profile?"selected":""}>${r}</option>`).join("");
    $("c-extra").value = CFG.system_prompt_extra || "";
    $("c-effort").value = CFG.agent ? CFG.agent.effort : "high";
    $("c-perm").value = CFG.tools.permissions.default;
    $("c-maxit").value = CFG.agent ? CFG.agent.max_iterations : 50;
  }
  $("c-save").onclick = async () => {
    const profiles = {};
    ROLES.forEach((r) => profiles[r] = {});
    document.querySelectorAll("#profiles [data-role]").forEach((el) => {
      if (el.value) profiles[el.dataset.role][el.dataset.k] = el.value;
    });
    const payload = {
      profiles, default_profile: $("c-default").value,
      system_prompt_extra: $("c-extra").value, effort: $("c-effort").value,
      permission_default: $("c-perm").value, max_iterations: Number($("c-maxit").value),
    };
    const r = await (await fetch("/api/config", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)})).json();
    $("c-status").textContent = r.status === "ok" ? "Saved to " + r.saved_to : "Error";
  };

  loadMetrics(); loadTasks(); loadConfig();
  setInterval(loadMetrics, 3000);
</script>
</body>
</html>
"""


def create_app(config: Config):
    import asyncio as _asyncio
    from pathlib import Path

    from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse

    from ..config import SPECIALIST_ROLES
    from ..metrics import METRICS
    from ..scheduling import ScheduledTask, ScheduleStore

    app = FastAPI(title="work-agent")

    def _store() -> ScheduleStore:
        return ScheduleStore(Path(config.workdir) / ".work-agent")

    @app.get("/")
    async def index() -> "HTMLResponse":
        return HTMLResponse(_INDEX_HTML)

    @app.get("/dashboard")
    async def dashboard() -> "HTMLResponse":
        return HTMLResponse(_DASHBOARD_HTML)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "provider": config.provider}

    # --- dashboard API ---------------------------------------------------

    @app.get("/api/metrics")
    async def api_metrics() -> dict:
        return await _asyncio.get_running_loop().run_in_executor(None, METRICS.snapshot)

    @app.get("/api/config")
    async def api_config_get() -> dict:
        return {
            "config": config.to_dict(),
            "roles": ["chat", *SPECIALIST_ROLES],
            "providers": ["anthropic", "deepseek", "openai_compatible"],
        }

    @app.post("/api/config")
    async def api_config_post(payload: dict = Body(...)) -> dict:
        config.update_from(payload)
        path = config.save()
        return {"status": "ok", "saved_to": path, "config": config.to_dict()}

    @app.get("/api/schedules")
    async def api_schedules() -> dict:
        from dataclasses import asdict

        return {"tasks": [asdict(t) for t in _store().load()]}

    @app.post("/api/schedules")
    async def api_schedule_add(body: dict = Body(...)) -> dict:
        from ..scheduling import is_valid_cron

        cron = (body.get("cron") or "").strip()
        task = (body.get("task") or "").strip()
        if not cron or not task:
            return {"status": "error", "message": "cron and task are required"}
        if not is_valid_cron(cron):
            return {"status": "error", "message": f"invalid cron: {cron}"}
        delivery = body.get("delivery") or {"type": "log"}
        created = _store().add(
            ScheduledTask(cron=cron, task=task, delivery=delivery, timezone=body.get("timezone"))
        )
        return {"status": "ok", "id": created.id, "next_run": created.next_run}

    @app.post("/api/schedules/{task_id}/{action}")
    async def api_schedule_toggle(task_id: str, action: str) -> dict:
        if action not in ("enable", "disable"):
            return {"status": "error", "message": "action must be enable or disable"}
        ok = _store().set_enabled(task_id, action == "enable")
        return {"status": "ok" if ok else "error"}

    @app.delete("/api/schedules/{task_id}")
    async def api_schedule_delete(task_id: str) -> dict:
        ok = _store().remove(task_id)
        return {"status": "ok" if ok else "error"}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: "WebSocket") -> None:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(msg: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, msg)

        events = AgentEvents(
            on_text=lambda t: emit({"type": "text", "text": t}),
            on_tool_call=lambda c: emit(
                {"type": "tool_call", "name": c.name, "arguments": c.arguments}
            ),
            on_tool_result=lambda n, r: emit(
                {"type": "tool_result", "name": n, "is_error": r.is_error}
            ),
            on_denied=lambda c: emit({"type": "denied", "name": c.name}),
            on_compaction=lambda n: emit({"type": "compaction", "messages": n}),
        )

        try:
            agent = build_agent(config, events=events, confirm=auto_allow)
        except RuntimeError as e:
            await websocket.send_json({"type": "error", "text": str(e)})
            await websocket.close()
            return

        async def drainer() -> None:
            while True:
                msg = await queue.get()
                await websocket.send_json(msg)

        try:
            while True:
                raw = await websocket.receive_text()
                task = (json.loads(raw).get("task") or "").strip()
                if not task:
                    continue
                drain_task = asyncio.create_task(drainer())
                try:
                    final = await loop.run_in_executor(None, agent.run_turn, task)
                    await asyncio.sleep(0.05)  # let trailing events flush
                    while not queue.empty():
                        await asyncio.sleep(0.01)
                except Exception as e:  # noqa: BLE001
                    final = f"[error: {e}]"
                finally:
                    drain_task.cancel()
                await websocket.send_json({"type": "done", "text": final})
        except WebSocketDisconnect:
            return

    return app


def run_web(config: Config, host: str, port: int) -> None:
    try:
        import uvicorn
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Web extras not installed. Run: pip install 'work-agent[web]'"
        ) from e
    uvicorn.run(create_app(config), host=host, port=port)
