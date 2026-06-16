FROM python:3.12-slim

# Common CLI tools the agent may need at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user; /workspace is the mount point for the agent's working files.
RUN useradd --create-home --uid 1000 agent \
    && mkdir -p /workspace \
    && chown agent:agent /workspace

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

USER agent
WORKDIR /workspace

ENTRYPOINT ["work-agent"]
CMD ["chat"]
