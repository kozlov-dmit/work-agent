"""Tool interface and execution context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ToolContext:
    """Ambient state passed to every tool invocation."""

    workdir: Path


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
