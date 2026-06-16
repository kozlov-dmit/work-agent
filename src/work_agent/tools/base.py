"""Tool interface and execution context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolContext:
    """Ambient state passed to every tool invocation.

    ``config`` and ``registry`` let self-management tools (``configure``)
    inspect and mutate the running agent; ``state_dir`` is the persistent
    directory used for provisioning and saved config.
    """

    workdir: Path
    state_dir: Path | None = None
    config: Any | None = None  # work_agent.config.Config
    registry: Any | None = None  # work_agent.tools.registry.ToolRegistry


@dataclass
class ToolOutput:
    content: str
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict
    parallel_safe: bool  # read-only tools may run concurrently

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput: ...
