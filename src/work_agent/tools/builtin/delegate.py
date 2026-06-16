"""Delegate a subtask to a purpose-specific model (model routing by role)."""

from __future__ import annotations

from ..base import ToolContext, ToolOutput

_ROLES = ("search", "development", "analysis")
_MAX_DEPTH = 1  # the chat agent (depth 0) may delegate; sub-agents may not


class DelegateTool:
    name = "delegate"
    description = (
        "Delegate a focused subtask to a specialist model configured for a purpose: "
        "'search' (web/research), 'development' (coding), or 'analysis' (data "
        "analysis). The specialist runs with its own model and the same tools, then "
        "returns its result. Use it for substantial subtasks that benefit from a "
        "purpose-specific model; keep the conversation yourself."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "role": {"type": "string", "enum": list(_ROLES)},
            "task": {
                "type": "string",
                "description": "Self-contained instructions for the specialist.",
            },
        },
        "required": ["role", "task"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        from ...agent import Agent
        from ...providers import build_provider

        parent = ctx.agent
        if parent is None or ctx.config is None:
            return ToolOutput("Delegation is unavailable in this context.", is_error=True)
        if getattr(parent, "depth", 0) >= _MAX_DEPTH:
            return ToolOutput("Max delegation depth reached.", is_error=True)

        role = args["role"]
        task = args.get("task", "").strip()
        if not task:
            return ToolOutput("'task' is required", is_error=True)

        sub_config = ctx.config.profile(role)
        try:
            provider = build_provider(sub_config)
        except (RuntimeError, ValueError) as e:
            return ToolOutput(f"Cannot start '{role}' specialist: {e}", is_error=True)

        sub = Agent(
            provider=provider,
            registry=parent.registry.clone_without("delegate"),
            policy=parent.policy,
            workdir=parent.workdir,
            max_iterations=parent.max_iterations,
            config=sub_config,
            state_dir=parent.state_dir,
            profile_role=role,
            depth=getattr(parent, "depth", 0) + 1,
        )
        try:
            result = sub.run_turn(task)
        except Exception as e:  # noqa: BLE001 - surface specialist failure to the caller
            return ToolOutput(f"Specialist '{role}' failed: {e}", is_error=True)
        return ToolOutput(f"[{role} specialist result]\n{result}")
