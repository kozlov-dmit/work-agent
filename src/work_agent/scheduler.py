"""Background scheduler that fires due cron tasks and delivers their results.

Runs as an asyncio loop (embedded in the Telegram bot, or standalone via
`work-agent scheduler`). On each tick it reloads the persisted schedules — so
tasks added at runtime are picked up — advances any due task's next-run time
immediately (to avoid double-firing), then runs it in a worker thread and awaits
delivery.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from .config import Config
from .scheduling import ScheduledTask, ScheduleStore, next_run_after, now_in

_TELEGRAM_LIMIT = 3500

DeliverFn = Callable[[ScheduledTask, str], Awaitable[None]]


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


@dataclass
class Scheduler:
    config: Config
    state_dir: Path
    deliver: DeliverFn
    tick_seconds: int = 30

    async def run(self) -> None:
        while True:
            try:
                await self.tick_once()
            except Exception:  # noqa: BLE001 - a bad task must not kill the loop
                pass
            await asyncio.sleep(self.tick_seconds)

    async def tick_once(self) -> None:
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
            result = await loop.run_in_executor(
                None, _run_one_turn, self.config, task.task
            )
        except Exception as e:  # noqa: BLE001
            result = f"[scheduled task failed: {e}]"
        try:
            await self.deliver(task, result)
        except Exception:  # noqa: BLE001
            pass
