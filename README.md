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
- **Permission policy.** Per-tool `allow` / `ask` / `deny` gating, with an
  interactive prompt and a `--yolo` auto-approve mode.
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

## Quick start (Docker)

```bash
cp .env.example .env          # add your API key
cp config.example.yaml config.yaml
mkdir -p workspace            # files the agent works on
docker compose run --rm work-agent chat
docker compose run --rm work-agent run "create a hello.py and run it"
```

## Configuration

Defaults < `config.yaml` < environment variables < CLI flags. See
[config.example.yaml](config.example.yaml). Point at a local model by switching
`provider` to `openai_compatible` and setting `base_url`.

## Tests

```bash
pip install -e ".[dev]"
pytest
```
