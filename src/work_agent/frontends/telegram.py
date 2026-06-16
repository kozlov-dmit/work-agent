"""Telegram bot frontend: chat with the agent from Telegram.

An alternative to the web server — same agent, same tools. Each Telegram chat
gets its own persistent agent session. Agent turns run in a thread; tool
activity is streamed back as messages.

Requires the ``telegram`` extra and a bot token in ``TELEGRAM_BOT_TOKEN``.
"""

from __future__ import annotations

import asyncio
import os

from pathlib import Path

from ..agent import Agent, AgentEvents
from ..config import Config
from ..permissions import auto_allow
from ..runtime import build_agent

_MAX_MSG = 3500  # Telegram caps messages at 4096 chars; leave headroom.


def _chunk(text: str) -> list[str]:
    return [text[i : i + _MAX_MSG] for i in range(0, len(text), _MAX_MSG)] or [""]


def run_telegram(config: Config) -> None:
    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Telegram extras not installed. Run: pip install 'work-agent[telegram]'"
        ) from e

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing bot token: set $TELEGRAM_BOT_TOKEN")

    from ..metrics import METRICS
    from ..scheduler import start_background_scheduler
    from ..sessions import SessionStore

    state_dir = Path(config.workdir) / ".work-agent"
    METRICS.configure(state_dir)
    METRICS.start_system_reporter("telegram")
    start_background_scheduler(config)  # standby scheduler (leader-elected)
    store = SessionStore(state_dir)
    agents: dict[int, Agent] = {}

    def session_id(chat_id: int) -> str:
        return f"telegram-{chat_id}"

    def get_agent(chat_id: int, bot, loop: asyncio.AbstractEventLoop) -> Agent:
        if chat_id not in agents:
            def send(text: str) -> None:
                asyncio.run_coroutine_threadsafe(bot.send_message(chat_id, text), loop)

            events = AgentEvents(
                on_tool_call=lambda c: send(f"→ {c.name}"),
                on_tool_result=lambda n, r: send(("✗ " if r.is_error else "✓ ") + n),
                on_denied=lambda c: send(f"denied: {c.name}"),
            )
            agent = build_agent(config, events=events, confirm=auto_allow)
            # Restore prior conversation so the bot remembers across restarts.
            agent.history = store.load(session_id(chat_id))
            # Scheduled tasks created from this chat are delivered back here.
            agent.delivery = {"type": "telegram", "target": chat_id}
            agents[chat_id] = agent
        return agents[chat_id]

    async def start(update: "Update", _ctx: "ContextTypes.DEFAULT_TYPE") -> None:
        await update.message.reply_text(
            "work-agent ready. Send a task. /reset to clear this chat's history."
        )

    async def reset(update: "Update", _ctx: "ContextTypes.DEFAULT_TYPE") -> None:
        chat_id = update.effective_chat.id
        agents.pop(chat_id, None)
        store.clear(session_id(chat_id))
        await update.message.reply_text("History cleared.")

    async def on_message(update: "Update", ctx: "ContextTypes.DEFAULT_TYPE") -> None:
        chat_id = update.effective_chat.id
        task = update.message.text.strip()
        if not task:
            return
        loop = asyncio.get_running_loop()
        agent = get_agent(chat_id, ctx.bot, loop)
        await ctx.bot.send_chat_action(chat_id, "typing")
        try:
            final = await loop.run_in_executor(None, agent.run_turn, task)
        except Exception as e:  # noqa: BLE001
            final = f"[error: {e}]"
        # Persist the updated history so it survives a bot/container restart.
        store.save(session_id(chat_id), agent.history)
        for part in _chunk(final or "(no output)"):
            await update.message.reply_text(part)

    # The cron scheduler runs as its own process/service (avoids double-firing
    # if both the bot and a standalone scheduler polled the shared store).
    # Tasks created from a chat are delivered back to it by that scheduler.
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling()
