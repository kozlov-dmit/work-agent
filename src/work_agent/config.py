"""Configuration: defaults overlaid by config.yaml then environment variables.

The agent can rewrite its own config (via the ``configure`` tool), so config is
also serializable back to disk. ``source_path`` remembers where to save.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_TOOLS = [
    "bash",
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    "http_request",
    "install_tool",
    "configure",
    "skill",
    "skill_write",
    "delegate",
]

# Specialist roles the agent can delegate to via the `delegate` tool.
SPECIALIST_ROLES = ("search", "development", "analysis")

# Where to look for a config file when none is passed explicitly, and where the
# agent saves self-configuration by default.
_DEFAULT_SAVE_PATH = "/workspace/.work-agent/config.yaml"


def _config_candidates() -> list[str]:
    return [
        os.environ.get("WORK_AGENT_CONFIG", ""),
        _DEFAULT_SAVE_PATH,
        "config.yaml",
    ]


@dataclass
class Config:
    provider: str = "anthropic"  # anthropic | openai_compatible
    model: str | None = None
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None

    effort: str = "high"
    max_iterations: int = 50

    # Conversation compaction: when estimated history tokens exceed the
    # threshold, older turns are summarized and recent turns kept verbatim.
    compaction_enabled: bool = True
    compaction_threshold_tokens: int = 40000
    compaction_keep_recent: int = 12

    enabled_tools: list[str] = field(default_factory=lambda: list(_DEFAULT_TOOLS))
    permission_default: str = "ask"  # allow | ask | deny
    permission_overrides: dict[str, str] = field(default_factory=dict)

    # Per-purpose model routing. The primary loop runs `default_profile`; the
    # `delegate` tool routes subtasks to a named profile (search/development/
    # analysis/...). Each profile may override provider/model/api_key_env/
    # base_url/effort; unset fields fall back to the top-level values.
    default_profile: str = "chat"
    profiles: dict[str, dict] = field(default_factory=dict)

    workdir: str = "/workspace"

    # Where this config was loaded from / should be saved to (not serialized).
    source_path: str | None = None

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        chosen = path
        if chosen is None:
            chosen = next((p for p in _config_candidates() if p and Path(p).exists()), None)

        data: dict = {}
        if chosen and Path(chosen).exists():
            data = yaml.safe_load(Path(chosen).read_text()) or {}

        cfg = cls()
        cfg.provider = data.get("provider", cfg.provider)
        cfg.model = data.get("model", cfg.model)
        cfg.api_key_env = data.get("api_key_env", cfg.api_key_env)
        cfg.base_url = data.get("base_url", cfg.base_url)

        agent = data.get("agent", {})
        cfg.effort = agent.get("effort", cfg.effort)
        cfg.max_iterations = agent.get("max_iterations", cfg.max_iterations)

        compaction = data.get("compaction", {})
        cfg.compaction_enabled = compaction.get("enabled", cfg.compaction_enabled)
        cfg.compaction_threshold_tokens = compaction.get(
            "threshold_tokens", cfg.compaction_threshold_tokens
        )
        cfg.compaction_keep_recent = compaction.get("keep_recent", cfg.compaction_keep_recent)

        tools = data.get("tools", {})
        cfg.enabled_tools = tools.get("enabled", cfg.enabled_tools)
        perms = tools.get("permissions", {})
        cfg.permission_default = perms.get("default", cfg.permission_default)
        cfg.permission_overrides = perms.get("overrides", cfg.permission_overrides)

        cfg.default_profile = data.get("default_profile", cfg.default_profile)
        cfg.profiles = data.get("profiles", cfg.profiles)

        cfg.workdir = data.get("sandbox", {}).get("workdir", cfg.workdir)

        # Environment overrides (highest precedence).
        cfg.provider = os.environ.get("WORK_AGENT_PROVIDER", cfg.provider)
        cfg.model = os.environ.get("WORK_AGENT_MODEL", cfg.model)
        cfg.base_url = os.environ.get("WORK_AGENT_BASE_URL", cfg.base_url)
        if "WORK_AGENT_API_KEY_ENV" in os.environ:
            cfg.api_key_env = os.environ["WORK_AGENT_API_KEY_ENV"]

        # Remember where to persist self-configuration.
        cfg.source_path = chosen or os.environ.get("WORK_AGENT_CONFIG") or None
        return cfg

    def profile(self, role: str) -> "Config":
        """Return a copy of this config with the named profile's overrides applied.

        Unknown roles return the base config unchanged, so delegation still works
        (using the default model) even when a profile isn't configured.
        """
        eff = copy.copy(self)
        p = self.profiles.get(role)
        if not p:
            return eff

        prov = p.get("provider", self.provider)
        eff.provider = prov
        # When switching provider without naming a model, let the new provider
        # use its own default rather than carrying over the chat model.
        if "model" in p:
            eff.model = p["model"]
        elif prov != self.provider:
            eff.model = None
        if "api_key_env" in p:
            eff.api_key_env = p["api_key_env"]
        elif prov != self.provider:
            # Sentinel: build_provider auto-resolves the provider's default key env.
            eff.api_key_env = "ANTHROPIC_API_KEY"
        if "base_url" in p:
            eff.base_url = p["base_url"]
        elif prov != self.provider:
            eff.base_url = None
        eff.effort = p.get("effort", self.effort)
        return eff

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "agent": {"max_iterations": self.max_iterations, "effort": self.effort},
            "compaction": {
                "enabled": self.compaction_enabled,
                "threshold_tokens": self.compaction_threshold_tokens,
                "keep_recent": self.compaction_keep_recent,
            },
            "default_profile": self.default_profile,
            "profiles": self.profiles,
            "tools": {
                "enabled": self.enabled_tools,
                "permissions": {
                    "default": self.permission_default,
                    "overrides": self.permission_overrides,
                },
            },
            "sandbox": {"workdir": self.workdir},
        }

    def save(self, path: str | None = None) -> str:
        target = Path(path or self.source_path or _DEFAULT_SAVE_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True))
        self.source_path = str(target)
        return str(target)
