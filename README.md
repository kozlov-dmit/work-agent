# work-agent

A dockerized, provider-agnostic LLM agent that performs arbitrary actions as an
assistant — similar in spirit to hermes-agent / openclaw. It runs in a
container, connects to a configured LLM (Anthropic Claude or any
OpenAI-compatible endpoint), and accomplishes tasks by calling tools (shell,
files, HTTP, and extensible plugins / MCP).

See [DESIGN.md](DESIGN.md) for the full architecture.

## Features

- **Provider-agnostic.** One agent loop over Anthropic (official `anthropic`
  SDK, default `claude-opus-4-8`), **DeepSeek** (`deepseek-chat` by default), and
  any OpenAI-compatible endpoint (official `openai` SDK — vLLM, Ollama,
  OpenRouter). Selected via config.
- **Built-in tools.** `bash`, `read`, `write`, `edit`, `glob`, `grep`,
  `http_request`. File tools are confined to the working directory.
- **Self-provisioning & self-configuration.** The agent can install its own
  tools (`install_tool` — apt/pip/npm) and edit its own config (`configure` —
  enable/disable tools, change model/effort/permissions). Installs persist
  across container restarts; tool enable/disable takes effect immediately.
- **Skills.** Reusable task instructions the agent reads on demand (`skill`) and
  authors itself (`skill_write`) — it captures your corrections into skills so it
  improves over time. Skills persist across sessions.
- **Per-purpose model routing.** Configure different LLMs for different purposes
  (chat, search, development, analysis). The conversational model orchestrates
  and routes focused subtasks to the right specialist via the `delegate` tool.
- **Conversation compaction.** Long histories are automatically summarized
  (provider-agnostic) past a configurable threshold, keeping recent turns
  verbatim — so sessions don't blow the context window.
- **Permission policy.** Per-tool `allow` / `ask` / `deny` gating, with an
  interactive prompt and a `--yolo` auto-approve mode.
- **Multiple frontends.** CLI (REPL / one-shot), a **web chat server**, and a
  **Telegram bot** — all driving the same agent.
- **Runs in Docker.** Isolated container, non-root user, `/workspace` mount.
- **Extensible.** Plugin and MCP tool sources are planned (see DESIGN.md).

## Quick start (local)

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
work-agent chat
# or one-shot:
work-agent run "summarize the files in this directory"
work-agent tools list
```

## Frontends

The same agent is reachable three ways:

```bash
# 1. CLI REPL (default)
work-agent chat

# 2. Web chat server — open http://localhost:8000
pip install -e ".[web]"
work-agent serve --host 0.0.0.0 --port 8000

# 3. Telegram bot (alternative to the web server)
pip install -e ".[telegram]"
export TELEGRAM_BOT_TOKEN=123456:ABC...
work-agent telegram
```

The web UI is a single page that submits tasks over a WebSocket and streams the
agent's text and tool activity live. The Telegram bot gives each chat its own
session and **persists that chat's history** to
`/workspace/.work-agent/sessions/telegram-<chat_id>.json`, so it remembers the
conversation across bot/container restarts (`/reset` clears it). Both frontends
run tools with auto-approve (the container is the isolation boundary); `deny`
overrides in config still apply.

> History persistence is scoped to Telegram (a genuinely long-lived,
> cross-restart channel). CLI and web keep history in memory for the session
> only. Durable, reusable knowledge is captured separately as skills.

## Quick start (Docker)

```bash
cp .env.example .env          # add your API key
cp config.example.yaml config.yaml
mkdir -p workspace            # files the agent works on
docker compose run --rm work-agent chat
docker compose run --rm work-agent run "create a hello.py and run it"
```

## Self-provisioning & self-configuration

The agent can extend and reconfigure itself at runtime:

- **`install_tool`** installs `apt` / `pip` / `npm` packages into the container.
  Each install is recorded in `/workspace/.work-agent/provisioning.json`, and the
  Docker entrypoint replays it via `work-agent bootstrap` on startup — so
  self-installed tools survive container recreation (the `/workspace` volume
  persists the manifest).
- **`configure`** reads/writes the agent's own config: `enable_tool` /
  `disable_tool` (applied to the live tool registry immediately) and `set`
  (model, provider, base_url, effort, max_iterations, permission_default —
  persisted; some apply on next start).

Both are mutating tools and default to the `ask` permission (auto-approved in the
web/Telegram frontends; the container is the isolation boundary). The image
grants the `agent` user passwordless `sudo` so `apt` installs work — treat the
container as single-tenant and untrusted-by-default.

## Skills

Skills are reusable, task-specific instructions stored as
`/workspace/.work-agent/skills/<name>/SKILL.md` (YAML frontmatter + markdown
body), so they survive container restarts. Each skill's name and description are
listed in the system prompt; the agent loads the full body on demand:

- **`skill`** (read-only) — `list` available skills, `read` one's full content.
- **`skill_write`** — `create` a new skill, `append` a correction/note to an
  existing one, or `edit` it.

The agent is instructed to read a matching skill before doing a task it covers,
and to persist your corrections and reusable procedures as skills — so feedback
in one session improves behavior in later ones. `skill` defaults to `allow`;
`skill_write` is mutating and defaults to `ask`.

## Configuration

Defaults < `config.yaml` < environment variables < CLI flags. See
[config.example.yaml](config.example.yaml).

- **DeepSeek:** set `provider: deepseek` and `DEEPSEEK_API_KEY` (defaults to
  `deepseek-chat`; use `deepseek-chat` for tool use — `deepseek-reasoner` has
  limited function-calling support).
- **Local / other:** set `provider: openai_compatible` with `base_url` (e.g. a
  local Ollama or vLLM server).

Each provider has a default API-key env var (`ANTHROPIC_API_KEY`,
`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`), used automatically when `api_key_env` is
left at its default.

### Per-purpose model routing

Use `profiles` to give each purpose its own LLM, and `default_profile` for the
primary conversation:

```yaml
default_profile: chat
profiles:
  chat:        { provider: anthropic, model: claude-opus-4-8 }
  search:      { provider: deepseek,  model: deepseek-chat }
  development: { provider: anthropic, model: claude-opus-4-8, effort: xhigh }
  analysis:    { provider: openai_compatible, model: llama3.1,
                 base_url: http://host.docker.internal:11434/v1 }
```

The chat model runs the conversation and calls `delegate(role, task)` to hand a
focused subtask to the `search` / `development` / `analysis` specialist, which
runs with its own model and the same tools and returns its result. A profile
inherits any field it doesn't set from the top-level config; an unconfigured
role falls back to the default model. The specialist's own tool calls stay
subject to the permission policy.

## Tests

```bash
pip install -e ".[dev]"
pytest
```
