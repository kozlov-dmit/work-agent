"""Command-line entry point: chat (REPL), run (one-shot), tools list."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

from .agent import Agent, AgentEvents
from .config import Config
from .permissions import auto_allow
from .runtime import build_agent
from .tools import ToolRegistry, build_registry

console = Console()


def _build_agent(config: Config, yolo: bool) -> Agent:
    def confirm(name: str, args: dict) -> bool:
        console.print(f"[yellow]Tool request:[/] {name} {args}")
        return Confirm.ask("Allow?", default=False)

    events = AgentEvents(
        on_text=lambda t: console.print(t),
        on_tool_call=lambda c: console.print(f"[cyan]→ {c.name}[/] {c.arguments}"),
        on_tool_result=lambda n, r: console.print(
            f"[green]✓ {n}[/]" if not r.is_error else f"[red]✗ {n}[/]"
        ),
        on_denied=lambda c: console.print(f"[red]denied: {c.name}[/]"),
        on_compaction=lambda n: console.print(f"[dim]🗜 compacted history ({n} messages)[/]"),
    )

    return build_agent(
        config,
        events=events,
        confirm=auto_allow if yolo else confirm,
    )


def cmd_chat(config: Config, yolo: bool) -> int:
    agent = _build_agent(config, yolo)
    console.print(f"[bold]work-agent[/] ({config.provider}). Type 'exit' to quit.")
    while True:
        try:
            user = console.input("[bold blue]you ›[/] ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        if user.strip() in {"exit", "quit"}:
            return 0
        if not user.strip():
            continue
        agent.run_turn(user)
    return 0


def cmd_run(config: Config, task: str, yolo: bool) -> int:
    agent = _build_agent(config, yolo)
    final = agent.run_turn(task)
    console.print(f"\n[bold]Result:[/]\n{final}")
    return 0


def cmd_tools(config: Config) -> int:
    registry: ToolRegistry = build_registry(config.enabled_tools)
    for name in registry.names():
        tool = registry.get(name)
        console.print(f"[bold]{name}[/] — {tool.description if tool else ''}")
    return 0


def cmd_serve(config: Config, host: str, port: int) -> int:
    from .frontends.web import run_web

    console.print(f"[bold]work-agent[/] web chat on http://{host}:{port}")
    run_web(config, host, port)
    return 0


def cmd_telegram(config: Config) -> int:
    from .frontends.telegram import run_telegram

    console.print("[bold]work-agent[/] Telegram bot starting (polling)…")
    run_telegram(config)
    return 0


def cmd_bootstrap(config: Config) -> int:
    """Replay the self-provisioning manifest (run at container startup)."""
    from .provisioning import Provisioning

    state_dir = Path(config.workdir) / ".work-agent"
    report = Provisioning(state_dir).apply_all()
    console.print(report or "[dim]nothing to provision[/]")
    return 0


def cmd_scheduler(config: Config) -> int:
    """Run the background cron scheduler (fires due tasks, delivers results)."""
    import asyncio
    import functools
    import os

    from .scheduler import Scheduler, default_deliver

    state_dir = Path(config.workdir) / ".work-agent"
    bot = None
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        try:
            from telegram import Bot

            bot = Bot(token)
        except ImportError:
            console.print("[yellow]Telegram not installed; telegram deliveries fall back to log.[/]")

    deliver = functools.partial(default_deliver, state_dir=state_dir, bot=bot)
    scheduler = Scheduler(config=config, state_dir=state_dir, deliver=deliver)
    console.print("[bold]work-agent[/] scheduler running. Ctrl-C to stop.")
    try:
        asyncio.run(scheduler.run())
    except KeyboardInterrupt:
        return 0
    return 0


def cmd_schedule(config: Config, action: str, task_id: str | None) -> int:
    from .scheduling import ScheduleStore

    store = ScheduleStore(Path(config.workdir) / ".work-agent")
    if action == "list":
        tasks = store.load()
        if not tasks:
            console.print("[dim](no scheduled tasks)[/]")
        for t in tasks:
            state = "on" if t.enabled else "off"
            console.print(
                f"[bold]{t.id}[/] [{state}] '{t.cron}' → {t.delivery.get('type')} | "
                f"next {t.next_run or '?'} | {t.task[:60]}"
            )
        return 0
    if action == "remove":
        ok = store.remove(task_id or "")
        console.print("removed" if ok else f"[red]no such task: {task_id}[/]")
        return 0 if ok else 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="work-agent")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--yolo", action="store_true", help="Auto-approve all tool calls")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("chat", help="Interactive REPL")
    p_run = sub.add_parser("run", help="Run a one-shot task")
    p_run.add_argument("task", help="The task description")
    tools_parser = sub.add_parser("tools", help="Tool commands")
    tools_sub = tools_parser.add_subparsers(dest="tools_command", required=True)
    tools_sub.add_parser("list", help="List available tools")

    p_serve = sub.add_parser("serve", help="Run the web chat server")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("telegram", help="Run the Telegram bot (TELEGRAM_BOT_TOKEN)")
    sub.add_parser("bootstrap", help="Replay self-provisioned tools (startup hook)")
    sub.add_parser("scheduler", help="Run the background cron scheduler")

    sched_parser = sub.add_parser("schedule", help="Inspect/manage scheduled tasks")
    sched_sub = sched_parser.add_subparsers(dest="schedule_command", required=True)
    sched_sub.add_parser("list", help="List scheduled tasks")
    p_sched_rm = sched_sub.add_parser("remove", help="Remove a scheduled task")
    p_sched_rm.add_argument("id", help="Task id")

    args = parser.parse_args(argv)
    config = Config.load(args.config)

    try:
        if args.command == "chat":
            return cmd_chat(config, args.yolo)
        if args.command == "run":
            return cmd_run(config, args.task, args.yolo)
        if args.command == "tools":
            return cmd_tools(config)
        if args.command == "serve":
            return cmd_serve(config, args.host, args.port)
        if args.command == "telegram":
            return cmd_telegram(config)
        if args.command == "bootstrap":
            return cmd_bootstrap(config)
        if args.command == "scheduler":
            return cmd_scheduler(config)
        if args.command == "schedule":
            return cmd_schedule(config, args.schedule_command, getattr(args, "id", None))
    except RuntimeError as e:
        console.print(f"[red]Error:[/] {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
