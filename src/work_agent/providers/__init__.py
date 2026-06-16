"""LLM provider abstraction and concrete backends."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .base import (
    LLMProvider,
    LLMResponse,
    Message,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)

if TYPE_CHECKING:
    from ..config import Config

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "Message",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Usage",
    "build_provider",
]

# Default env var holding each provider's API key, used when the config leaves
# api_key_env at its (Anthropic) default but selects another provider.
_DEFAULT_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai_compatible": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def build_provider(config: "Config") -> LLMProvider:
    """Construct the provider selected in config, reading the API key from env."""
    key_env = config.api_key_env
    if key_env == "ANTHROPIC_API_KEY" and config.provider != "anthropic":
        key_env = _DEFAULT_KEY_ENV.get(config.provider, key_env)
    api_key = os.environ.get(key_env, "")

    if config.provider == "anthropic":
        from .anthropic import AnthropicProvider

        if not api_key:
            raise RuntimeError(f"Missing API key: set ${key_env}")
        return AnthropicProvider(config, api_key)

    if config.provider == "deepseek":
        from .deepseek import DeepSeekProvider

        if not api_key:
            raise RuntimeError(f"Missing API key: set ${key_env}")
        return DeepSeekProvider(config, api_key)

    if config.provider == "openai_compatible":
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(config, api_key)

    raise ValueError(f"Unknown provider: {config.provider!r}")
