"""Durable conversation history for long-lived chat sessions (Telegram).

Serializes the agent's normalized message history to a JSON file per session,
under the persistent state directory so it survives process/container restarts.
Scope is intentionally narrow: only frontends with genuinely long-lived,
cross-restart conversations (Telegram) use this. One-shot and ephemeral
frontends keep history in memory only.
"""

from __future__ import annotations

import json
from pathlib import Path

from .providers.base import Message, ToolCall, ToolResult


def to_jsonable(messages: list[Message]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        out.append(
            {
                "role": m.role,
                "text": m.text,
                "tool_calls": [
                    {"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls
                ],
                "tool_results": [
                    {"tool_call_id": r.tool_call_id, "content": r.content, "is_error": r.is_error}
                    for r in m.tool_results
                ],
            }
        )
    return out


def from_jsonable(data: list[dict]) -> list[Message]:
    messages: list[Message] = []
    for d in data:
        messages.append(
            Message(
                role=d.get("role", "user"),
                text=d.get("text"),
                tool_calls=[
                    ToolCall(id=c["id"], name=c["name"], arguments=c.get("arguments", {}))
                    for c in d.get("tool_calls", [])
                ],
                tool_results=[
                    ToolResult(
                        tool_call_id=r["tool_call_id"],
                        content=r.get("content", ""),
                        is_error=r.get("is_error", False),
                    )
                    for r in d.get("tool_results", [])
                ],
            )
        )
    return messages


class SessionStore:
    """Loads/saves per-session message history as JSON under ``<state_dir>/sessions``."""

    def __init__(self, state_dir: Path) -> None:
        self.dir = Path(state_dir) / "sessions"

    def _path(self, session_id: str) -> Path:
        # session_id is caller-controlled (e.g. "telegram-<chat_id>"); keep it a
        # single path component so it can't escape the sessions directory.
        safe = session_id.replace("/", "_").replace("..", "_")
        return self.dir / f"{safe}.json"

    def load(self, session_id: str) -> list[Message]:
        path = self._path(session_id)
        if not path.exists():
            return []
        try:
            return from_jsonable(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, KeyError):
            return []

    def save(self, session_id: str, messages: list[Message]) -> None:
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_jsonable(messages), ensure_ascii=False), encoding="utf-8")

    def clear(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)
