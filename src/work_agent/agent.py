"""The agent loop: drive the LLM, execute tool calls, feed results back."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .permissions import PermissionPolicy
from .providers.base import LLMProvider, Message, ToolCall, ToolResult
from .skills import skills_system_section
from .tools import ToolContext, ToolRegistry

BASE_SYSTEM_PROMPT = (
    "You are work-agent, an autonomous assistant running inside a container. "
    "You accomplish the user's task by reasoning and calling tools. "
    "Prefer concrete actions over narration. When the task is done, stop and "
    "report the outcome plainly."
)

ROLE_INSTRUCTIONS = {
    "search": (
        "You are the research specialist. Find and synthesize information from the "
        "web and available sources, cite where it came from, and return concise findings."
    ),
    "development": (
        "You are the development specialist. Write, modify, and run code carefully; "
        "prefer minimal changes and verify with tests or execution where possible."
    ),
    "analysis": (
        "You are the data-analysis specialist. Inspect the data, compute results, "
        "and explain your findings with concrete evidence."
    ),
}


def _delegation_section(config) -> str:
    from .config import SPECIALIST_ROLES

    lines = []
    for role in SPECIALIST_ROLES:
        p = (config.profiles or {}).get(role) or {}
        provider = p.get("provider", config.provider)
        model = p.get("model") or "(default model)"
        lines.append(f"- {role}: {provider} / {model}")
    return (
        "\n\n## Specialist models\n"
        "You can route a focused subtask to a purpose-specific model with the "
        "`delegate` tool. Configured specialists:\n" + "\n".join(lines) + "\n"
        "Delegate substantial search / development / analysis subtasks; handle the "
        "conversation and orchestration yourself."
    )


@dataclass
class AgentEvents:
    """Callbacks for surfacing progress to a UI (all optional)."""

    on_text: Callable[[str], None] = lambda _t: None
    on_tool_call: Callable[[ToolCall], None] = lambda _c: None
    on_tool_result: Callable[[str, ToolResult], None] = lambda _n, _r: None
    on_denied: Callable[[ToolCall], None] = lambda _c: None
    on_compaction: Callable[[int], None] = lambda _n: None


@dataclass
class Agent:
    provider: LLMProvider
    registry: ToolRegistry
    policy: PermissionPolicy
    workdir: Path
    max_iterations: int = 50
    events: AgentEvents = field(default_factory=AgentEvents)
    history: list[Message] = field(default_factory=list)
    config: object | None = None  # work_agent.config.Config — for self-configuration
    state_dir: Path | None = None  # persistent dir for provisioning / saved config
    profile_role: str = "chat"  # which purpose this agent serves
    depth: int = 0  # delegation depth (0 = primary chat agent)
    compactor: object | None = None  # work_agent.context.Compactor
    delivery: dict | None = None  # default delivery target for scheduled tasks

    def system_prompt(self) -> str:
        role_intro = ROLE_INSTRUCTIONS.get(self.profile_role)
        prompt = f"{role_intro}\n\n{BASE_SYSTEM_PROMPT}" if role_intro else BASE_SYSTEM_PROMPT
        if self.state_dir is not None:
            prompt += skills_system_section(self.state_dir / "skills")
        if self.depth == 0 and self.config is not None and self.registry.get("delegate"):
            prompt += _delegation_section(self.config)
        return prompt

    def run_turn(self, user_input: str) -> str:
        """Run one user turn to completion, returning the final assistant text."""
        self.history.append(Message(role="user", text=user_input))
        ctx = ToolContext(
            workdir=self.workdir,
            state_dir=self.state_dir,
            config=self.config,
            registry=self.registry,
            agent=self,
            delivery=self.delivery,
        )
        final_text = ""
        system = self.system_prompt()

        for _ in range(self.max_iterations):
            if self.compactor is not None:
                self.history, compacted = self.compactor.maybe_compact(self.history)
                if compacted:
                    self.events.on_compaction(len(self.history))

            response = self.provider.complete(
                system=system,
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
