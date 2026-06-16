FROM python:3.12-slim

# Common CLI tools, plus sudo so the agent can self-install OS packages (apt).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates sudo \
    && rm -rf /var/lib/apt/lists/*

# Non-root user; /workspace is the mount point for the agent's working files.
RUN useradd --create-home --uid 1000 agent \
    && mkdir -p /workspace \
    && chown agent:agent /workspace \
    # Passwordless sudo so `install_tool` can run apt-get. The container is the
    # isolation boundary; treat it as single-tenant and untrusted-by-default.
    && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent

# Put user-level install targets on PATH so `pip install --user` and
# `npm install -g` (after the agent sets a user prefix) are usable.
ENV PATH="/home/agent/.local/bin:/home/agent/.npm-global/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web,telegram]"

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER agent
WORKDIR /workspace

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["chat"]
