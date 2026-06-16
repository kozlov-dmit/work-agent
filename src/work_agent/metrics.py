"""Process-wide runtime metrics: token usage, reliability, and system stats.

A single in-process collector accumulates LLM/tool counters (updated from the
agent loop). System stats (CPU/memory/net) are sampled on demand via psutil if
available. Metrics are per-process — the dashboard shows the process serving it.
"""

from __future__ import annotations

import threading
import time

from .providers.base import Usage


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self.llm_requests = 0
        self.llm_failures = 0
        self.llm_refusals = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.tool_calls = 0
        self.tool_errors = 0

    def record_llm(self, usage: Usage | None, ok: bool = True, refusal: bool = False) -> None:
        with self._lock:
            self.llm_requests += 1
            if not ok:
                self.llm_failures += 1
            if refusal:
                self.llm_refusals += 1
            if usage is not None:
                self.input_tokens += getattr(usage, "input_tokens", 0) or 0
                self.output_tokens += getattr(usage, "output_tokens", 0) or 0

    def record_tool(self, ok: bool = True) -> None:
        with self._lock:
            self.tool_calls += 1
            if not ok:
                self.tool_errors += 1

    def snapshot(self) -> dict:
        with self._lock:
            requests = self.llm_requests
            failures = self.llm_failures
            reliability = (requests - failures) / requests if requests else 1.0
            data = {
                "uptime_seconds": int(time.time() - self.started),
                "tokens": {
                    "input": self.input_tokens,
                    "output": self.output_tokens,
                    "total": self.input_tokens + self.output_tokens,
                },
                "llm": {
                    "requests": requests,
                    "failures": failures,
                    "refusals": self.llm_refusals,
                    "reliability": round(reliability, 4),
                },
                "tools": {"calls": self.tool_calls, "errors": self.tool_errors},
            }
        data["system"] = system_metrics()
        return data


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


# Process-global collector used across the agent loop and the dashboard.
METRICS = Metrics()
