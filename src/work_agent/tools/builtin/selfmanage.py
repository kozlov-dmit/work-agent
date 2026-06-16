"""Self-management tools: install software and edit the agent's own config.

These let the agent provision its container and reconfigure itself at runtime.
They are sensitive, so the default permission policy gates them with ``ask``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..base import ToolContext, ToolOutput

# Config keys the `configure set` action may change. Some apply live, others
# only take effect on the next start (noted in the result).
_SETTABLE = {
    "model": "next start",
    "provider": "next start",
    "base_url": "next start",
    "effort": "next start",
    "max_iterations": "live",
    "permission_default": "live",
}


class InstallTool:
    name = "install_tool"
    description = (
        "Install software into the agent's own container via a package manager. "
        "Installs immediately and records the packages so they are reinstalled "
        "automatically when the container restarts. Use this to give yourself "
        "tools you need (CLI utilities, libraries) before using them via bash."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "manager": {"type": "string", "enum": ["apt", "pip", "npm"]},
            "packages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Package names to install.",
            },
        },
        "required": ["manager", "packages"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        from ...provisioning import SUPPORTED, Provisioning

        manager = args["manager"]
        packages = args.get("packages") or []
        if manager not in SUPPORTED:
            return ToolOutput(f"Unsupported manager: {manager}", is_error=True)
        if not packages:
            return ToolOutput("No packages specified", is_error=True)

        state_dir = ctx.state_dir or (ctx.workdir / ".work-agent")
        code, out = Provisioning(state_dir).install(manager, packages, record=True)
        body = out.strip() or "(no output)"
        if len(body) > 20_000:
            body = body[:20_000] + "\n... [truncated]"
        suffix = "" if code == 0 else f"\n[install failed: exit {code}]"
        return ToolOutput(f"exit={code}\n{body}{suffix}", is_error=code != 0)


class ConfigureTool:
    name = "configure"
    description = (
        "Inspect or change your own configuration. Actions: 'get' returns the "
        "current config; 'enable_tool'/'disable_tool' turn a built-in tool on/off "
        "(takes effect immediately); 'set' changes a setting (model, provider, "
        "base_url, effort, max_iterations, permission_default). Changes are saved "
        "to the config file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get", "enable_tool", "disable_tool", "set"]},
            "tool": {"type": "string", "description": "Tool name for enable_tool/disable_tool."},
            "key": {"type": "string", "description": "Setting name for 'set'."},
            "value": {"type": "string", "description": "New value for 'set'."},
        },
        "required": ["action"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        cfg = ctx.config
        if cfg is None:
            return ToolOutput("No config is bound to this agent.", is_error=True)
        action = args["action"]

        if action == "get":
            return ToolOutput(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False))

        if action in ("enable_tool", "disable_tool"):
            return self._toggle_tool(action, args, ctx, cfg)

        if action == "set":
            return self._set(args, cfg)

        return ToolOutput(f"Unknown action: {action}", is_error=True)

    @staticmethod
    def _toggle_tool(action: str, args: dict, ctx: ToolContext, cfg) -> ToolOutput:
        from work_agent.tools.builtin import all_builtins

        name = args.get("tool")
        if not name:
            return ToolOutput("'tool' is required for this action", is_error=True)

        if action == "enable_tool":
            available = {t.name: t for t in all_builtins()}
            if name not in available:
                return ToolOutput(f"Unknown tool: {name}", is_error=True)
            if name not in cfg.enabled_tools:
                cfg.enabled_tools.append(name)
            if ctx.registry is not None and ctx.registry.get(name) is None:
                ctx.registry.register(available[name])
            verb = "enabled"
        else:
            if name in cfg.enabled_tools:
                cfg.enabled_tools.remove(name)
            if ctx.registry is not None:
                ctx.registry.remove(name)
            verb = "disabled"

        path = cfg.save()
        return ToolOutput(f"{verb} '{name}' (live). Saved to {path}.")

    @staticmethod
    def _set(args: dict, cfg) -> ToolOutput:
        key = args.get("key")
        value = args.get("value")
        if key not in _SETTABLE:
            return ToolOutput(
                f"Cannot set '{key}'. Allowed: {', '.join(_SETTABLE)}", is_error=True
            )
        if key == "max_iterations":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return ToolOutput("max_iterations must be an integer", is_error=True)
        setattr(cfg, key, value)
        path = cfg.save()
        when = _SETTABLE[key]
        note = "" if when == "live" else " (applies on next start)"
        return ToolOutput(f"set {key}={value}{note}. Saved to {path}.")
