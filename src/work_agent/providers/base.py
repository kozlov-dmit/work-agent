"""Provider-agnostic message and tool types, plus the LLMProvider protocol.

The agent keeps history in this normalized form; each provider serializes it
into its own native API shape and parses responses back into these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ToolCall:
    """A model's request to invoke a tool."""

    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """The outcome of executing a single ToolCall."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """A normalized conversation turn.

    - role "user":      free-form text in ``text``.
    - role "assistant": optional ``text`` plus zero or more ``tool_calls``.
    - role "tool":      one or more ``tool_results`` answering prior tool_calls.
    """

    role: str
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class ToolSpec:
    """Provider-agnostic tool declaration handed to the LLM."""

    name: str
    description: str
    input_schema: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens" | "refusal"
    usage: Usage


@runtime_checkable
class LLMProvider(Protocol):
    """A backend the agent can talk to (Anthropic, OpenAI-compatible, ...)."""

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        stream: bool = True,
    ) -> LLMResponse: ...
