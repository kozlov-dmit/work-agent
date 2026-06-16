"""Anthropic (Claude) provider built on the official ``anthropic`` SDK.

Uses native tool-use, adaptive thinking, and streaming so long responses don't
hit request timeouts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .base import LLMResponse, Message, ToolCall, ToolSpec, Usage

if TYPE_CHECKING:
    from ..config import Config

# Default Claude model. Adaptive thinking is the recommended mode on this family.
DEFAULT_MODEL = "claude-opus-4-8"

_STOP_REASON_MAP = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
    "stop_sequence": "end_turn",
    "pause_turn": "tool_use",
}


class AnthropicProvider:
    def __init__(self, config: "Config", api_key: str) -> None:
        import anthropic

        self._config = config
        self._model = config.model or DEFAULT_MODEL
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        stream: bool = True,
    ) -> LLMResponse:
        params: dict = {
            "model": self._model,
            "max_tokens": 16000 if not stream else 32000,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [self._to_anthropic(m) for m in messages],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self._config.effort},
        }
        if tools:
            params["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]

        if stream:
            with self._client.messages.stream(**params) as s:
                response = s.get_final_message()
        else:
            response = self._client.messages.create(**params)

        return self._parse(response)

    # -- serialization ---------------------------------------------------

    @staticmethod
    def _to_anthropic(m: Message) -> dict:
        if m.role == "tool":
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in m.tool_results
                ],
            }
        if m.role == "assistant":
            blocks: list[dict] = []
            if m.text:
                blocks.append({"type": "text", "text": m.text})
            for c in m.tool_calls:
                blocks.append(
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                )
            return {"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]}
        # user
        return {"role": "user", "content": m.text or ""}

    @staticmethod
    def _parse(response) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=args))

        usage = Usage(
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
        )
        return LLMResponse(
            text="".join(text_parts) or None,
            tool_calls=tool_calls,
            stop_reason=_STOP_REASON_MAP.get(response.stop_reason, "end_turn"),
            usage=usage,
        )
