"""Tool for scheduling background cron tasks from a conversation."""

from __future__ import annotations

from pathlib import Path

from ..base import ToolContext, ToolOutput


def _state_dir(ctx: ToolContext) -> Path:
    return ctx.state_dir or (ctx.workdir / ".work-agent")


class ScheduleTool:
    name = "schedule"
    description = (
        "Schedule a recurring background task with a cron expression, or manage "
        "existing schedules. The task is a natural-language instruction run "
        "autonomously on the schedule (e.g. 'send a news digest'), and the result "
        "is delivered to the user. Actions: 'list', 'add' (cron, task, [delivery], "
        "[timezone]), 'remove' (id), 'enable' (id), 'disable' (id). Cron format: "
        "'minute hour day month weekday' — e.g. '0 9 * * *' is every day at 09:00."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "remove", "enable", "disable"]},
            "cron": {"type": "string", "description": "Cron expression for 'add'."},
            "task": {"type": "string", "description": "Instruction to run for 'add'."},
            "delivery": {
                "type": "string",
                "enum": ["telegram", "log"],
                "description": "Where to send results (default: current chat if Telegram, else log).",
            },
            "timezone": {"type": "string", "description": "IANA tz, e.g. Europe/Moscow."},
            "id": {"type": "string", "description": "Task id for remove/enable/disable."},
        },
        "required": ["action"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        from ...scheduling import ScheduledTask, ScheduleStore, is_valid_cron

        store = ScheduleStore(_state_dir(ctx))
        action = args["action"]

        if action == "list":
            tasks = store.load()
            if not tasks:
                return ToolOutput("(no scheduled tasks)")
            lines = []
            for t in tasks:
                state = "on" if t.enabled else "off"
                lines.append(
                    f"{t.id} [{state}] '{t.cron}' → {t.delivery.get('type')} | "
                    f"next: {t.next_run or '?'} | {t.task[:60]}"
                )
            return ToolOutput("\n".join(lines))

        if action == "add":
            cron = args.get("cron")
            task = args.get("task")
            if not cron or not task:
                return ToolOutput("'cron' and 'task' are required for add", is_error=True)
            if not is_valid_cron(cron):
                return ToolOutput(f"Invalid cron expression: {cron}", is_error=True)

            delivery = self._resolve_delivery(args.get("delivery"), ctx)
            if delivery is None:
                return ToolOutput(
                    "Telegram delivery isn't available here; pass delivery='log'.", is_error=True
                )

            created = store.add(
                ScheduledTask(
                    cron=cron, task=task, delivery=delivery, timezone=args.get("timezone")
                )
            )
            from ...scheduler import scheduler_alive

            warn = (
                ""
                if scheduler_alive(_state_dir(ctx))
                else " WARNING: no scheduler is currently running, so this task is "
                "saved but won't run until a scheduler/service starts."
            )
            return ToolOutput(
                f"Scheduled task {created.id}: '{cron}' → {delivery['type']}. "
                f"Next run: {created.next_run}.{warn}"
            )

        task_id = args.get("id")
        if not task_id:
            return ToolOutput("'id' is required for this action", is_error=True)

        if action == "remove":
            ok = store.remove(task_id)
            return ToolOutput(f"Removed {task_id}." if ok else f"No such task: {task_id}",
                              is_error=not ok)
        if action in ("enable", "disable"):
            ok = store.set_enabled(task_id, action == "enable")
            return ToolOutput(f"{action}d {task_id}." if ok else f"No such task: {task_id}",
                              is_error=not ok)

        return ToolOutput(f"Unknown action: {action}", is_error=True)

    @staticmethod
    def _resolve_delivery(requested: str | None, ctx: ToolContext) -> dict | None:
        hint = ctx.delivery or {}
        want = requested or hint.get("type") or "log"
        if want == "telegram":
            target = hint.get("target")
            if target is None:
                return None
            return {"type": "telegram", "target": target}
        return {"type": "log"}
