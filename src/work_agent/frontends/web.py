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
<header>work-agent — chat</header>
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


def create_app(config: Config):
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="work-agent")

    @app.get("/")
    async def index() -> "HTMLResponse":
        return HTMLResponse(_INDEX_HTML)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "provider": config.provider}

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
