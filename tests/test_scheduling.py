import time
from datetime import datetime
from pathlib import Path

from work_agent.scheduling import (
    ScheduledTask,
    ScheduleStore,
    is_valid_cron,
    next_run_after,
)
from work_agent.tools.base import ToolContext
from work_agent.tools.builtin.schedule import ScheduleTool


def test_cron_validation():
    assert is_valid_cron("0 9 * * *")
    assert not is_valid_cron("not a cron")


def test_next_run_after_is_in_future():
    after = datetime(2026, 1, 1, 8, 0, 0)
    nxt = next_run_after("0 9 * * *", None, after)
    assert nxt == datetime(2026, 1, 1, 9, 0, 0).isoformat()


def test_store_add_load_remove(tmp_path: Path):
    store = ScheduleStore(tmp_path)
    assert store.load() == []

    created = store.add(ScheduledTask(cron="0 9 * * *", task="news digest"))
    assert created.next_run is not None  # computed on add
    tasks = store.load()
    assert len(tasks) == 1
    assert tasks[0].task == "news digest"

    assert store.set_enabled(created.id, False)
    assert store.load()[0].enabled is False

    assert store.remove(created.id)
    assert store.load() == []
    assert not store.remove("missing")


def test_schedule_tool_add_defaults_to_telegram_from_context(tmp_path: Path):
    ctx = ToolContext(
        workdir=tmp_path,
        state_dir=tmp_path,
        delivery={"type": "telegram", "target": 4242},
    )
    out = ScheduleTool().run(
        {"action": "add", "cron": "0 9 * * *", "task": "morning news"}, ctx
    )
    assert not out.is_error
    tasks = ScheduleStore(tmp_path).load()
    assert len(tasks) == 1
    assert tasks[0].delivery == {"type": "telegram", "target": 4242}


def test_schedule_tool_telegram_requested_without_context_errors(tmp_path: Path):
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path)  # no delivery hint
    out = ScheduleTool().run(
        {"action": "add", "cron": "0 9 * * *", "task": "x", "delivery": "telegram"}, ctx
    )
    assert out.is_error


def test_schedule_tool_defaults_to_log(tmp_path: Path):
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path)
    out = ScheduleTool().run({"action": "add", "cron": "0 9 * * *", "task": "x"}, ctx)
    assert not out.is_error
    assert ScheduleStore(tmp_path).load()[0].delivery == {"type": "log"}


def test_schedule_tool_invalid_cron(tmp_path: Path):
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path)
    out = ScheduleTool().run({"action": "add", "cron": "bogus", "task": "x"}, ctx)
    assert out.is_error


def test_lease_single_leader(tmp_path: Path):
    from work_agent.scheduler import Lease, scheduler_alive

    lease = Lease(tmp_path / "scheduler.db", ttl=60)
    assert scheduler_alive(tmp_path) is False
    assert lease.acquire("a") is True       # a becomes leader
    assert lease.acquire("a") is True       # a renews
    assert lease.acquire("b") is False      # b cannot steal a live lease
    assert scheduler_alive(tmp_path) is True


def test_lease_failover_after_expiry(tmp_path: Path):
    from work_agent.scheduler import Lease

    short = Lease(tmp_path / "scheduler.db", ttl=0.05)
    assert short.acquire("a") is True
    time.sleep(0.1)  # lease expires
    other = Lease(tmp_path / "scheduler.db", ttl=60)
    assert other.acquire("b") is True       # b takes over once a's lease expired


def test_scheduler_standby_does_not_fire_without_lease(tmp_path: Path, monkeypatch):
    import asyncio

    from work_agent import scheduler as sched_mod
    from work_agent.config import Config
    from work_agent.scheduler import Lease, Scheduler

    store = ScheduleStore(tmp_path)
    store.add(ScheduledTask(cron="* * * * *", task="do it"))
    tasks = store.load()
    tasks[0].next_run = datetime(2000, 1, 1).isoformat()
    store.save(tasks)

    # Another process already holds the lease.
    assert Lease(tmp_path / "scheduler.db", ttl=60).acquire("someone-else") is True

    monkeypatch.setattr(sched_mod, "_run_one_turn", lambda config, text: "RESULT")
    fired = []

    async def deliver(task, result):
        fired.append(task.id)

    scheduler = Scheduler(config=Config(), state_dir=tmp_path, deliver=deliver)

    async def main():
        await scheduler.tick_once()
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert fired == []  # standby (non-leader) must not fire


def test_scheduler_fires_due_task(tmp_path: Path, monkeypatch):
    import asyncio

    from work_agent import scheduler as sched_mod
    from work_agent.config import Config
    from work_agent.scheduler import Scheduler

    store = ScheduleStore(tmp_path)
    created = store.add(ScheduledTask(cron="* * * * *", task="do it"))
    # Force it overdue.
    tasks = store.load()
    tasks[0].next_run = datetime(2000, 1, 1).isoformat()
    store.save(tasks)

    monkeypatch.setattr(sched_mod, "_run_one_turn", lambda config, text: f"RESULT:{text}")
    delivered: list[tuple[str, str]] = []

    async def deliver(task, result):
        delivered.append((task.id, result))

    scheduler = Scheduler(config=Config(), state_dir=tmp_path, deliver=deliver)

    async def main():
        await scheduler.tick_once()
        await asyncio.sleep(0.05)  # let the fired task complete

    asyncio.run(main())

    assert delivered == [(created.id, "RESULT:do it")]
    # next_run advanced into the future so it won't immediately refire
    assert datetime.fromisoformat(store.load()[0].next_run) > datetime.now()
