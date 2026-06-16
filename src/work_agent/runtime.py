"""Shared agent construction used by every frontend (CLI, web, Telegram)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .agent import Agent, AgentEvents
from .config import Config
from .permissions import PermissionPolicy
from .providers import build_provider
from .tools import build_registry


def build_agent(
    config: Config,
    events: AgentEvents | None = None,
    confirm: Callable[[str, dict], bool] | None = None,
) -> Agent:
    """Construct an Agent from config.

    ``confirm`` resolves ``ask`` permission decisions; non-interactive frontends
    pass ``permissions.auto_allow``. ``deny`` overrides in config still apply.
    """
    from .permissions import auto_allow

    provider = build_provider(config)
    registry = build_registry(config.enabled_tools)
    policy = PermissionPolicy(
        default=config.permission_default,
        overrides=config.permission_overrides,
        confirm=confirm or auto_allow,
    )
    return Agent(
        provider=provider,
        registry=registry,
        policy=policy,
        workdir=Path(config.workdir),
        max_iterations=config.max_iterations,
        events=events or AgentEvents(),
    )
