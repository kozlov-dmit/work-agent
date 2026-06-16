from pathlib import Path

from work_agent.agent import Agent
from work_agent.config import Config
from work_agent.permissions import auto_allow
from work_agent.permissions import PermissionPolicy
from work_agent.providers.base import LLMResponse, Usage
from work_agent.tools import build_registry
from work_agent.tools.base import ToolContext
from work_agent.tools.builtin.delegate import DelegateTool


def test_profile_switches_provider_and_defaults_model():
    cfg = Config()
    cfg.provider = "anthropic"
    cfg.model = "claude-opus-4-8"
    cfg.profiles = {"search": {"provider": "deepseek"}}  # no model named
    eff = cfg.profile("search")
    assert eff.provider == "deepseek"
    assert eff.model is None  # let DeepSeek use its own default
    assert eff.api_key_env == "ANTHROPIC_API_KEY"  # sentinel → auto-resolved later


def test_profile_keeps_model_when_same_provider():
    cfg = Config()
    cfg.profiles = {"development": {"effort": "xhigh"}}
    eff = cfg.profile("development")
    assert eff.provider == cfg.provider
    assert eff.model == cfg.model
    assert eff.effort == "xhigh"


def test_unknown_profile_returns_base():
    cfg = Config()
    eff = cfg.profile("nope")
    assert eff.provider == cfg.provider
    assert eff.model == cfg.model


class _FakeProvider:
    def __init__(self, label: str):
        self.label = label

    def complete(self, system, messages, tools, stream=True):
        return LLMResponse(
            text=f"{self.label} handled: {messages[-1].text}",
            tool_calls=[],
            stop_reason="end_turn",
            usage=Usage(),
        )


def test_delegate_routes_to_profile(monkeypatch, tmp_path: Path):
    import work_agent.providers as providers

    captured = {}

    def fake_build_provider(eff_config):
        captured["provider"] = eff_config.provider
        return _FakeProvider(eff_config.provider)

    monkeypatch.setattr(providers, "build_provider", fake_build_provider)

    cfg = Config()
    cfg.profiles = {"development": {"provider": "deepseek", "model": "deepseek-chat"}}
    parent = Agent(
        provider=_FakeProvider("chat"),
        registry=build_registry(["read", "delegate"]),
        policy=PermissionPolicy("allow", {}, auto_allow),
        workdir=tmp_path,
        config=cfg,
        state_dir=tmp_path,
    )
    ctx = ToolContext(
        workdir=tmp_path, state_dir=tmp_path, config=cfg, registry=parent.registry, agent=parent
    )

    out = DelegateTool().run({"role": "development", "task": "write a function"}, ctx)
    assert not out.is_error
    assert captured["provider"] == "deepseek"
    assert "deepseek handled: write a function" in out.content


def test_delegate_depth_limit(tmp_path: Path):
    cfg = Config()
    parent = Agent(
        provider=_FakeProvider("x"),
        registry=build_registry(["delegate"]),
        policy=PermissionPolicy("allow", {}, auto_allow),
        workdir=tmp_path,
        config=cfg,
        state_dir=tmp_path,
        depth=1,  # already a sub-agent
    )
    ctx = ToolContext(workdir=tmp_path, config=cfg, registry=parent.registry, agent=parent)
    out = DelegateTool().run({"role": "search", "task": "x"}, ctx)
    assert out.is_error
