import pytest

from work_agent.config import Config
from work_agent.providers import build_provider
from work_agent.providers.deepseek import DeepSeekProvider


def test_deepseek_uses_default_model_and_key_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    cfg = Config()
    cfg.provider = "deepseek"
    cfg.model = None  # should fall back to deepseek-chat
    provider = build_provider(cfg)
    assert isinstance(provider, DeepSeekProvider)
    assert provider._model == "deepseek-chat"
    assert str(provider._client.base_url).startswith("https://api.deepseek.com")


def test_deepseek_respects_explicit_model(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    cfg = Config()
    cfg.provider = "deepseek"
    cfg.model = "deepseek-reasoner"
    provider = build_provider(cfg)
    assert provider._model == "deepseek-reasoner"


def test_deepseek_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = Config()
    cfg.provider = "deepseek"
    with pytest.raises(RuntimeError):
        build_provider(cfg)


def test_unknown_provider_raises():
    cfg = Config()
    cfg.provider = "nope"
    with pytest.raises(ValueError):
        build_provider(cfg)
