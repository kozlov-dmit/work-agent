"""Built-in tools shipped with the agent."""

from __future__ import annotations

from ..base import Tool
from .files import EditTool, GlobTool, GrepTool, ReadTool, WriteTool
from .http import HttpRequestTool
from .selfmanage import ConfigureTool, InstallTool
from .shell import BashTool
from .skills import SkillTool, SkillWriteTool


def all_builtins() -> list[Tool]:
    return [
        BashTool(),
        ReadTool(),
        WriteTool(),
        EditTool(),
        GlobTool(),
        GrepTool(),
        HttpRequestTool(),
        InstallTool(),
        ConfigureTool(),
        SkillTool(),
        SkillWriteTool(),
    ]
