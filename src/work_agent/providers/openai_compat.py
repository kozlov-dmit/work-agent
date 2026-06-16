"""OpenAI-compatible provider built on the official ``openai`` SDK.

Targets any ``/chat/completions`` endpoint via ``base_url`` — vLLM, Ollama,
OpenRouter, or hosted OpenAI-compatible APIs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .base import LLMResponse, Message, ToolCall, ToolSpec, Usage

if TYPE_CHECKING:
    from ..config import Config


class OpenAICompatProvider:
    def __init__(self, config: "Config", api_key: str) -> None:
        from openai import OpenAI

        self._config = config
        self._model = config.model or "gpt-4o-mini"
        # base_url may be None for the real OpenAI API; SDK handles that.
        self._client = OpenAI(api_key=api_key or "not-needed", base_url=config.base_url)

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        stream: bool = True,
    ) -> LLMResponse:
        payload: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            payload.extend(self._to_openai(m))

        params: dict = {"model": self._model, "messages": payload}
        if tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]

        # Tool-calling is simpler to assemble from a non-streamed response;
        # streaming can be added per-delta later without changing the interface.
        response = self._client.chat.completions.create(**params)
        return self._parse(response)

    # -- serialization ---------------------------------------------------

    @staticmethod
    def _to_openai(m: Message) -> list[dict]:
        if m.role == "tool":
            return [
                {"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content}
                for r in m.tool_results
            ]
        if m.role == "assistant":
            msg: dict = {"role": "assistant", "content": m.text or ""}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in m.tool_calls
                ]
            return [msg]
        return [{"role": "user", "content": m.text or ""}]

    @staticmethod
    def _parse(response) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        stop_reason = "tool_use" if tool_calls else "end_turn"
        if choice.finish_reason == "length":
            stop_reason = "max_tokens"

        usage = Usage(
            input_tokens=getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
            output_tokens=getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
        )
        return LLMResponse(
            text=msg.content or None,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )
