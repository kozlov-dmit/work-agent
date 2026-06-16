"""Shared, cross-process runtime metrics.

Counters (token usage, LLM reliability, tool calls) are persisted to a small
SQLite database in the state directory, which is a shared volume across the web,
Telegram, and scheduler containers — so the dashboard shows totals aggregated
from every process, not just its own.

System stats (CPU/memory/net) are sampled live via psutil and reflect the
process/container that serves the dashboard (they are not aggregated).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

from .providers.base import Usage

_DEFAULT_STATE_DIR = "/workspace/.work-agent"
_COUNTERS = (
    "llm_requests",
    "llm_failures",
    "llm_refusals",
    "input_tokens",
    "output_tokens",
    "tool_calls",
    "tool_errors",
)


class MetricsStore:
    """SQLite-backed counters shared across processes via the state volume."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None

    def configure(self, state_dir: str | Path) -> None:
        with self._lock:
            self._path = Path(state_dir) / "metrics.db"

    def _db_path(self) -> Path:
        if self._path is None:
            base = os.environ.get("WORK_AGENT_STATE_DIR", _DEFAULT_STATE_DIR)
            self._path = Path(base) / "metrics.db"
        return self._path

    def _connect(self) -> sqlite3.Connection:
        path = self._db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value REAL)")
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('started_at', ?)", (time.time(),)
        )
        return conn

    def _incr(self, deltas: dict[str, int]) -> None:
        deltas = {k: v for k, v in deltas.items() if v}
        if not deltas:
            return
        try:
            with self._connect() as conn:
                for key, value in deltas.items():
                    conn.execute(
                        "INSERT INTO counters(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = value + excluded.value",
                        (key, value),
                    )
        except sqlite3.Error:
            pass  # metrics must never break the agent

    def record_llm(self, usage: Usage | None, ok: bool = True, refusal: bool = False) -> None:
        deltas = {"llm_requests": 1}
        if not ok:
            deltas["llm_failures"] = 1
        if refusal:
            deltas["llm_refusals"] = 1
        if usage is not None:
            deltas["input_tokens"] = getattr(usage, "input_tokens", 0) or 0
            deltas["output_tokens"] = getattr(usage, "output_tokens", 0) or 0
        self._incr(deltas)

    def record_tool(self, ok: bool = True) -> None:
        deltas = {"tool_calls": 1}
        if not ok:
            deltas["tool_errors"] = 1
        self._incr(deltas)

    def snapshot(self) -> dict:
        counters = {k: 0 for k in _COUNTERS}
        started = time.time()
        try:
            with self._connect() as conn:
                for key, value in conn.execute("SELECT key, value FROM counters"):
                    if key in counters:
                        counters[key] = value
                row = conn.execute("SELECT value FROM meta WHERE key = 'started_at'").fetchone()
                if row:
                    started = row[0]
        except sqlite3.Error:
            pass

        requests = counters["llm_requests"]
        failures = counters["llm_failures"]
        reliability = (requests - failures) / requests if requests else 1.0
        return {
            "uptime_seconds": int(time.time() - started),
            "tokens": {
                "input": counters["input_tokens"],
                "output": counters["output_tokens"],
                "total": counters["input_tokens"] + counters["output_tokens"],
            },
            "llm": {
                "requests": requests,
                "failures": failures,
                "refusals": counters["llm_refusals"],
                "reliability": round(reliability, 4),
            },
            "tools": {"calls": counters["tool_calls"], "errors": counters["tool_errors"]},
            "system": system_metrics(),
        }


def system_metrics() -> dict:
    try:
        import psutil
    except ImportError:
        return {"available": False}

    vm = psutil.virtual_memory()
    net = psutil.net_io_counters()
    return {
        "available": True,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": vm.percent,
        "memory_used_mb": round(vm.used / 1_048_576, 1),
        "memory_total_mb": round(vm.total / 1_048_576, 1),
        "net_sent_mb": round(net.bytes_sent / 1_048_576, 1),
        "net_recv_mb": round(net.bytes_recv / 1_048_576, 1),
    }


# Process-global handle to the shared store, used across the agent loop and the
# dashboard. Point it at the state dir via `configure()`; otherwise it falls back
# to $WORK_AGENT_STATE_DIR or /workspace/.work-agent.
METRICS = MetricsStore()
