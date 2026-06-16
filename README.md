# work-agent

A dockerized, provider-agnostic LLM agent that performs arbitrary actions as an
assistant — similar in spirit to hermes-agent / openclaw. It runs in a
container, connects to a configured LLM (Anthropic Claude or any
OpenAI-compatible endpoint), and accomplishes tasks by calling tools (shell,
files, HTTP, and extensible plugins / MCP).

See [DESIGN.md](DESIGN.md) for the full architecture.

## Features

- **Provider-agnostic.** One agent loop over Anthropic (official `anthropic`
  SDK, default `claude-opus-4-8`) and OpenAI-compatible endpoints (official
  `openai` SDK — vLLM, Ollama, OpenRouter). Selected via config.
- **Built-in tools.** `bash`, `read`, `write`, `edit`, `glob`, `grep`,
  `http_request`. File tools are confined to the working directory.
- **Self-provisioning & self-configuration.** The agent can install its own
  tools (`install_tool` — apt/pip/npm) and edit its own config (`configure` —
  enable/disable tools, change model/effort/permissions). Installs persist
  across container restarts; tool enable/disable takes effect immediately.
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
session (`/reset` clears history). Both run tools with auto-approve (the
container is the isolation boundary); `deny` overrides in config still apply.

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

## Configuration

Defaults < `config.yaml` < environment variables < CLI flags. See
[config.example.yaml](config.example.yaml). Point at a local model by switching
`provider` to `openai_compatible` and setting `base_url`.

## Tests

```bash
pip install -e ".[dev]"
pytest
```
