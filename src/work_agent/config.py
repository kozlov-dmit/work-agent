"""Configuration: defaults overlaid by config.yaml then environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_TOOLS = ["bash", "read", "write", "edit", "glob", "grep", "http_request"]


@dataclass
class Config:
    provider: str = "anthropic"  # anthropic | openai_compatible
    model: str | None = None
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None

    effort: str = "high"
    max_iterations: int = 50

    enabled_tools: list[str] = field(default_factory=lambda: list(_DEFAULT_TOOLS))
    permission_default: str = "ask"  # allow | ask | deny
    permission_overrides: dict[str, str] = field(default_factory=dict)

    workdir: str = "/workspace"

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        data: dict = {}
        if path and Path(path).exists():
            data = yaml.safe_load(Path(path).read_text()) or {}

        cfg = cls()
        cfg.provider = data.get("provider", cfg.provider)
        cfg.model = data.get("model", cfg.model)
        cfg.api_key_env = data.get("api_key_env", cfg.api_key_env)
        cfg.base_url = data.get("base_url", cfg.base_url)

        agent = data.get("agent", {})
        cfg.effort = agent.get("effort", cfg.effort)
        cfg.max_iterations = agent.get("max_iterations", cfg.max_iterations)

        tools = data.get("tools", {})
        cfg.enabled_tools = tools.get("enabled", cfg.enabled_tools)
        perms = tools.get("permissions", {})
        cfg.permission_default = perms.get("default", cfg.permission_default)
        cfg.permission_overrides = perms.get("overrides", cfg.permission_overrides)

        cfg.workdir = data.get("sandbox", {}).get("workdir", cfg.workdir)

        # Environment overrides (highest precedence).
        cfg.provider = os.environ.get("WORK_AGENT_PROVIDER", cfg.provider)
        cfg.model = os.environ.get("WORK_AGENT_MODEL", cfg.model)
        cfg.base_url = os.environ.get("WORK_AGENT_BASE_URL", cfg.base_url)
        if "WORK_AGENT_API_KEY_ENV" in os.environ:
            cfg.api_key_env = os.environ["WORK_AGENT_API_KEY_ENV"]
        return cfg
