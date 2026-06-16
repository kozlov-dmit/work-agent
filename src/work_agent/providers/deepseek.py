"""DeepSeek provider.

DeepSeek exposes an OpenAI-compatible Chat Completions API, so this reuses the
OpenAI-compatible client (including its tool-use handling) and only supplies
DeepSeek's defaults: base URL and model.

Note: ``deepseek-chat`` supports function calling. ``deepseek-reasoner`` is a
reasoning model with limited/changing tool-call support — prefer ``deepseek-chat``
for tool-driven agent work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .openai_compat import OpenAICompatProvider

if TYPE_CHECKING:
    from ..config import Config

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class DeepSeekProvider(OpenAICompatProvider):
    def __init__(self, config: "Config", api_key: str) -> None:
        from openai import OpenAI

        self._config = config
        self._model = config.model or DEFAULT_MODEL
        self._client = OpenAI(api_key=api_key, base_url=config.base_url or DEFAULT_BASE_URL)
