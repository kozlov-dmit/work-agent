"""Background scheduler that fires due cron tasks and delivers their results.

The scheduler runs as its own service (`work-agent scheduler`). On each tick it
renews a heartbeat (an entry in SQLite) so other processes can tell whether a
scheduler is alive — the `schedule` tool refuses to add a task if none is. The
heartbeat is owner-scoped, so it also guards against accidentally running two
scheduler instances (only the heartbeat holder fires).
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from .config import Config
from .scheduling import ScheduledTask, ScheduleStore, next_run_after, now_in

_TELEGRAM_LIMIT = 3500
_LEASE_FILE = "scheduler.db"

DeliverFn = Callable[[ScheduledTask, str], Awaitable[None]]


# --- leader lease ------------------------------------------------------------


class Lease:
    """Owner-scoped heartbeat/lock in SQLite: liveness signal + single-fire guard."""

    def __init__(self, path: Path, ttl: float = 90.0) -> None:
        self.path = Path(path)
        self.ttl = ttl

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS lease "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), owner TEXT, expires_at REAL)"
        )
        return conn

    def acquire(self, owner: str) -> bool:
        """Claim/renew the heartbeat if free, expired, or already ours. Atomic."""
        now = time.time()
        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT owner, expires_at FROM lease WHERE id = 1").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO lease(id, owner, expires_at) VALUES (1, ?, ?)",
                        (owner, now + self.ttl),
                    )
                    ok = True
                elif row[0] == owner or row[1] is None or row[1] < now:
                    conn.execute(
                        "UPDATE lease SET owner = ?, expires_at = ? WHERE id = 1",
                        (owner, now + self.ttl),
                    )
                    ok = True
                else:
                    ok = False
                conn.execute("COMMIT")
                return ok
            finally:
                conn.close()
        except sqlite3.Error:
            return False  # on DB trouble, don't fire (prefer missed over double)

    def alive(self) -> bool:
        try:
            conn = self._connect()
            try:
                row = conn.execute("SELECT expires_at FROM lease WHERE id = 1").fetchone()
                return bool(row and row[0] and row[0] > time.time())
            finally:
                conn.close()
        except sqlite3.Error:
            return False


def scheduler_alive(state_dir: Path) -> bool:
    """True if some scheduler currently holds a live lease."""
    return Lease(Path(state_dir) / _LEASE_FILE).alive()


# --- delivery ----------------------------------------------------------------


def _format_message(task: ScheduledTask, result: str) -> str:
    return f"⏰ {task.task}\n\n{result}"


def write_log(state_dir: Path, task: ScheduledTask, result: str) -> Path:
    out = Path(state_dir) / "schedule-output" / task.id
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = out / f"{ts}.md"
    path.write_text(f"# {task.task}\n\n{result}\n", encoding="utf-8")
    return path


async def default_deliver(
    task: ScheduledTask, result: str, *, state_dir: Path, bot=None
) -> None:
    """Deliver to Telegram if configured and a bot is available, else to a log file."""
    delivery = task.delivery or {}
    if delivery.get("type") == "telegram" and delivery.get("target") is not None and bot is not None:
        try:
            msg = _format_message(task, result)
            async with bot:  # initialise/shutdown the Bot for a standalone send
                for i in range(0, len(msg), _TELEGRAM_LIMIT):
                    await bot.send_message(delivery["target"], msg[i : i + _TELEGRAM_LIMIT])
            return
        except Exception:  # noqa: BLE001 - fall back to a log file on any send failure
            pass
    write_log(state_dir, task, result)


def _run_one_turn(config: Config, task_text: str) -> str:
    from .runtime import build_agent

    agent = build_agent(config)  # non-interactive: ask-decisions auto-approve
    return agent.run_turn(task_text)


# --- scheduler ---------------------------------------------------------------


@dataclass
class Scheduler:
    config: Config
    state_dir: Path
    deliver: DeliverFn
    tick_seconds: int = 30
    owner: str = field(default_factory=lambda: uuid.uuid4().hex)
    _lease: Lease | None = None

    def __post_init__(self) -> None:
        ttl = max(60.0, self.tick_seconds * 3)
        self._lease = Lease(Path(self.state_dir) / _LEASE_FILE, ttl=ttl)

    async def run(self) -> None:
        while True:
            try:
                await self.tick_once()
            except Exception:  # noqa: BLE001 - a bad task must not kill the loop
                pass
            await asyncio.sleep(self.tick_seconds)

    async def tick_once(self) -> None:
        # Renew the heartbeat; if another scheduler instance holds it, stand by
        # (guards against accidentally running two schedulers).
        if self._lease is not None and not self._lease.acquire(self.owner):
            return

        store = ScheduleStore(self.state_dir)
        tasks = store.load()
        due: list[ScheduledTask] = []
        changed = False

        for t in tasks:
            if not t.enabled:
                continue
            now = now_in(t.timezone)
            if t.next_run is None:
                t.next_run = next_run_after(t.cron, t.timezone, now)
                changed = True
                continue
            if datetime.fromisoformat(t.next_run) <= now:
                t.last_run = now.isoformat()
                t.next_run = next_run_after(t.cron, t.timezone, now)
                changed = True
                due.append(t)

        if changed:
            store.save(tasks)
        for t in due:
            asyncio.create_task(self._fire(t))

    async def _fire(self, task: ScheduledTask) -> None:
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, _run_one_turn, self.config, task.task)
        except Exception as e:  # noqa: BLE001
            result = f"[scheduled task failed: {e}]"
        try:
            await self.deliver(task, result)
        except Exception:  # noqa: BLE001
            pass
