"""Conversation compaction.

When history grows past a threshold, summarize the older portion into a single
note and keep recent turns verbatim. Provider-agnostic — it uses the agent's own
LLM to produce the summary, so it works the same on Anthropic, DeepSeek, and
OpenAI-compatible backends.

Token counts are estimated cheaply (no provider tokenizer needed); the threshold
just needs headroom under the smallest model's context window.
"""

from __future__ import annotations

from dataclasses import dataclass

from .providers.base import LLMProvider, Message

SUMMARY_PREFIX = "[Summary of earlier conversation]\n"

_SUMMARY_SYSTEM = (
    "You compress conversation history. Produce a concise but complete summary "
    "that preserves: the user's goals and tasks, key decisions, important facts "
    "discovered, actions taken and their results, user corrections and "
    "preferences, and the current state and next steps. Omit small talk. Use "
    "compact prose or bullet points."
)


def estimate_tokens(messages: list[Message]) -> int:
    """Rough token estimate (~4 chars/token) across text, tool calls, results."""
    chars = 0
    for m in messages:
        if m.text:
            chars += len(m.text)
        for c in m.tool_calls:
            chars += len(c.name) + len(str(c.arguments))
        for r in m.tool_results:
            chars += len(r.content)
        chars += 8  # per-message overhead
    return chars // 4


def render_transcript(messages: list[Message]) -> str:
    lines: list[str] = []
    for m in messages:
        if m.role == "user":
            lines.append(f"User: {m.text or ''}")
        elif m.role == "assistant":
            if m.text:
                lines.append(f"Assistant: {m.text}")
            for c in m.tool_calls:
                lines.append(f"Assistant called {c.name}({c.arguments})")
        elif m.role == "tool":
            for r in m.tool_results:
                status = " [error]" if r.is_error else ""
                lines.append(f"Tool result{status}: {r.content}")
    return "\n".join(lines)


def find_cut_index(messages: list[Message], keep_recent: int) -> int:
    """Index where the verbatim-kept suffix begins.

    Snaps forward to the next ``user`` message so a complete turn boundary is
    kept — never splitting an assistant tool_use from its tool results. Returns 0
    (compact nothing) if no clean boundary exists.
    """
    n = len(messages)
    target = n - keep_recent
    if target <= 0:
        return 0
    i = target
    while i < n and messages[i].role != "user":
        i += 1
    if i >= n:
        return 0
    return i


@dataclass
class Compactor:
    provider: LLMProvider
    threshold_tokens: int = 40000
    keep_recent: int = 12
    enabled: bool = True

    def maybe_compact(self, history: list[Message]) -> tuple[list[Message], bool]:
        """Return (possibly-compacted history, whether compaction happened)."""
        if not self.enabled or estimate_tokens(history) < self.threshold_tokens:
            return history, False
        cut = find_cut_index(history, self.keep_recent)
        if cut <= 0:
            return history, False
        older, recent = history[:cut], history[cut:]
        summary = self._summarize(older)
        summary_msg = Message(role="user", text=SUMMARY_PREFIX + summary)
        return [summary_msg, *recent], True

    def _summarize(self, messages: list[Message]) -> str:
        transcript = render_transcript(messages)
        prompt = Message(role="user", text=f"Summarize the conversation so far:\n\n{transcript}")
        try:
            resp = self.provider.complete(_SUMMARY_SYSTEM, [prompt], [], stream=False)
        except Exception:  # noqa: BLE001 - never let summarization break the turn
            return "(summary unavailable)"
        return (resp.text or "").strip() or "(summary unavailable)"
