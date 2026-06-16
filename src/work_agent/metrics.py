"""Shared, cross-process runtime metrics.

Counters (token usage, LLM reliability, tool calls) are persisted to a small
SQLite database in the state directory — a shared volume across the web,
Telegram, and scheduler containers — so the dashboard shows totals aggregated
from every process.

System stats (CPU/memory/net) are also collected from every process: each
long-running service reports its own sample on an interval, keyed by service
name, so the dashboard shows the same metrics broken down per service.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

from .providers.base import Usage

_DEFAULT_STATE_DIR = "/workspace/.work-agent"
_MB = 1_048_576
_COUNTERS = (
    "llm_requests",
    "llm_failures",
    "llm_refusals",
    "input_tokens",
    "output_tokens",
    "tool_calls",
    "tool_errors",
)


def process_system_sample() -> dict | None:
    """A system-metrics sample for the current process / container."""
    try:
        import psutil
    except ImportError:
        return None
    proc = psutil.Process()
    net = psutil.net_io_counters()
    return {
        "cpu_percent": round(proc.cpu_percent(interval=0.1), 1),
        "mem_percent": round(proc.memory_percent(), 1),
        "mem_rss_mb": round(proc.memory_info().rss / _MB, 1),
        "net_sent_mb": round(net.bytes_sent / _MB, 1),
        "net_recv_mb": round(net.bytes_recv / _MB, 1),
    }


class MetricsStore:
    """SQLite-backed counters + per-service system samples, shared via the volume."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._reporter: threading.Thread | None = None

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
            "CREATE TABLE IF NOT EXISTS system_samples ("
            "service TEXT PRIMARY KEY, cpu_percent REAL, mem_percent REAL, mem_rss_mb REAL, "
            "net_sent_mb REAL, net_recv_mb REAL, updated_at REAL)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('started_at', ?)", (time.time(),)
        )
        return conn

    # -- counters --------------------------------------------------------

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

    # -- per-service system samples -------------------------------------

    def record_system(self, service: str) -> None:
        sample = process_system_sample()
        if sample is None:
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO system_samples"
                    "(service, cpu_percent, mem_percent, mem_rss_mb, net_sent_mb, net_recv_mb, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(service) DO UPDATE SET cpu_percent=excluded.cpu_percent, "
                    "mem_percent=excluded.mem_percent, mem_rss_mb=excluded.mem_rss_mb, "
                    "net_sent_mb=excluded.net_sent_mb, net_recv_mb=excluded.net_recv_mb, "
                    "updated_at=excluded.updated_at",
                    (
                        service,
                        sample["cpu_percent"],
                        sample["mem_percent"],
                        sample["mem_rss_mb"],
                        sample["net_sent_mb"],
                        sample["net_recv_mb"],
                        time.time(),
                    ),
                )
        except sqlite3.Error:
            pass

    def start_system_reporter(self, service: str, interval: float = 5.0) -> None:
        """Start a daemon thread that reports this process's system sample."""
        if self._reporter is not None:
            return

        def loop() -> None:
            while True:
                self.record_system(service)
                time.sleep(interval)

        self._reporter = threading.Thread(target=loop, name=f"metrics-{service}", daemon=True)
        self._reporter.start()

    # -- read ------------------------------------------------------------

    def snapshot(self) -> dict:
        counters = {k: 0 for k in _COUNTERS}
        started = time.time()
        systems: list[dict] = []
        now = time.time()
        try:
            with self._connect() as conn:
                for key, value in conn.execute("SELECT key, value FROM counters"):
                    if key in counters:
                        counters[key] = value
                row = conn.execute("SELECT value FROM meta WHERE key = 'started_at'").fetchone()
                if row:
                    started = row[0]
                for r in conn.execute(
                    "SELECT service, cpu_percent, mem_percent, mem_rss_mb, net_sent_mb, "
                    "net_recv_mb, updated_at FROM system_samples ORDER BY service"
                ):
                    systems.append(
                        {
                            "service": r[0],
                            "cpu_percent": r[1],
                            "mem_percent": r[2],
                            "mem_rss_mb": r[3],
                            "net_sent_mb": r[4],
                            "net_recv_mb": r[5],
                            "age_seconds": int(now - (r[6] or now)),
                        }
                    )
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
            "systems": systems,
        }


# Process-global handle to the shared store. Point it at the state dir via
# `configure()`; otherwise it falls back to $WORK_AGENT_STATE_DIR or
# /workspace/.work-agent.
METRICS = MetricsStore()
