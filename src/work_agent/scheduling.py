"""Scheduled background tasks (cron).

A scheduled task pairs a cron expression with a natural-language task prompt and
a delivery target. A background scheduler runs due tasks autonomously (a fresh
agent turn each time) and delivers the result — to a Telegram chat or a log file.

Tasks persist as JSON under the state directory so schedules survive restarts.
Times are interpreted in the task's `timezone` (IANA) if set, otherwise the
container's local time.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass
class ScheduledTask:
    cron: str
    task: str
    delivery: dict = field(default_factory=lambda: {"type": "log"})
    timezone: str | None = None
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: str = ""
    last_run: str | None = None
    next_run: str | None = None


def _tz(name: str | None):
    return ZoneInfo(name) if name else None


def now_in(tz_name: str | None) -> datetime:
    return datetime.now(_tz(tz_name))


def is_valid_cron(expr: str) -> bool:
    from croniter import croniter

    return croniter.is_valid(expr)


def next_run_after(cron: str, tz_name: str | None, after: datetime) -> str:
    """Next fire time strictly after ``after``, as an ISO timestamp."""
    from croniter import croniter

    nxt = croniter(cron, after).get_next(datetime)
    return nxt.isoformat()


class ScheduleStore:
    def __init__(self, state_dir: Path) -> None:
        self.path = Path(state_dir) / "schedules.json"

    def load(self) -> list[ScheduledTask]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [ScheduledTask(**d) for d in data]

    def save(self, tasks: list[ScheduledTask]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(t) for t in tasks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, task: ScheduledTask) -> ScheduledTask:
        tasks = self.load()
        task.created_at = task.created_at or now_in(task.timezone).isoformat()
        task.next_run = next_run_after(task.cron, task.timezone, now_in(task.timezone))
        tasks.append(task)
        self.save(tasks)
        return task

    def remove(self, task_id: str) -> bool:
        tasks = self.load()
        kept = [t for t in tasks if t.id != task_id]
        if len(kept) == len(tasks):
            return False
        self.save(kept)
        return True

    def set_enabled(self, task_id: str, enabled: bool) -> bool:
        tasks = self.load()
        found = False
        for t in tasks:
            if t.id == task_id:
                t.enabled = enabled
                found = True
        if found:
            self.save(tasks)
        return found
