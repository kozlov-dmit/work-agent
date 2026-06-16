"""The agent loop: drive the LLM, execute tool calls, feed results back."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .permissions import PermissionPolicy
from .providers.base import LLMProvider, Message, ToolCall, ToolResult
from .tools import ToolContext, ToolRegistry

SYSTEM_PROMPT = (
    "You are work-agent, an autonomous assistant running inside a container. "
    "You accomplish the user's task by reasoning and calling tools. "
    "Prefer concrete actions over narration. When the task is done, stop and "
    "report the outcome plainly."
)


@dataclass
class AgentEvents:
    """Callbacks for surfacing progress to a UI (all optional)."""

    on_text: Callable[[str], None] = lambda _t: None
    on_tool_call: Callable[[ToolCall], None] = lambda _c: None
    on_tool_result: Callable[[str, ToolResult], None] = lambda _n, _r: None
    on_denied: Callable[[ToolCall], None] = lambda _c: None


@dataclass
class Agent:
    provider: LLMProvider
    registry: ToolRegistry
    policy: PermissionPolicy
    workdir: Path
    max_iterations: int = 50
    events: AgentEvents = field(default_factory=AgentEvents)
    history: list[Message] = field(default_factory=list)

    def run_turn(self, user_input: str) -> str:
        """Run one user turn to completion, returning the final assistant text."""
        self.history.append(Message(role="user", text=user_input))
        ctx = ToolContext(workdir=self.workdir)
        final_text = ""

        for _ in range(self.max_iterations):
            response = self.provider.complete(
                system=SYSTEM_PROMPT,
                messages=self.history,
                tools=self.registry.specs(),
            )

            if response.text:
                self.events.on_text(response.text)
                final_text = response.text

            self.history.append(
                Message(role="assistant", text=response.text, tool_calls=response.tool_calls)
            )

            if response.stop_reason == "refusal":
                return final_text or "[The model refused this request.]"
            if not response.tool_calls:
                return final_text

            results = [self._execute(call, ctx) for call in response.tool_calls]
            self.history.append(Message(role="tool", tool_results=results))

        return final_text or "[Reached max iterations without finishing.]"

    def _execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        self.events.on_tool_call(call)
        tool = self.registry.get(call.name)
        if tool is None:
            return ToolResult(call.id, f"Unknown tool: {call.name}", is_error=True)

        if not self.policy.allowed(call.name, call.arguments):
            self.events.on_denied(call)
            return ToolResult(call.id, "Denied by permission policy.", is_error=True)

        try:
            output = tool.run(call.arguments, ctx)
        except Exception as e:  # noqa: BLE001 - surface any tool failure to the model
            return ToolResult(call.id, f"Tool error: {e}", is_error=True)

        result = ToolResult(call.id, output.content, is_error=output.is_error)
        self.events.on_tool_result(call.name, result)
        return result
