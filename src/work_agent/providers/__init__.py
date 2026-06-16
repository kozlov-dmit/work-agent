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


def build_provider(config: "Config") -> LLMProvider:
    """Construct the provider selected in config, reading the API key from env."""
    api_key = os.environ.get(config.api_key_env, "")

    if config.provider == "anthropic":
        from .anthropic import AnthropicProvider

        if not api_key:
            raise RuntimeError(f"Missing API key: set ${config.api_key_env}")
        return AnthropicProvider(config, api_key)

    if config.provider == "openai_compatible":
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(config, api_key)

    raise ValueError(f"Unknown provider: {config.provider!r}")
