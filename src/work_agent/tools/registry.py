"""Central tool registry: built-ins, plugins, and (later) MCP tools."""

from __future__ import annotations

from ..providers.base import ToolSpec
from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name=t.name, description=t.description, input_schema=t.input_schema)
            for t in self._tools.values()
        ]


def build_registry(enabled: list[str]) -> ToolRegistry:
    """Build a registry containing the enabled built-in tools.

    Plugin and MCP sources are layered on top of this in later phases.
    """
    from .builtin import all_builtins

    registry = ToolRegistry()
    available = {t.name: t for t in all_builtins()}
    for name in enabled:
        tool = available.get(name)
        if tool is not None:
            registry.register(tool)
    return registry
