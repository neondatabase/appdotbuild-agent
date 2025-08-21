FROM python:3.12-slim AS prod

# Install Docker CE CLI for Dagger engine compatibility
# Dagger requires Docker CLI to manage containers, but the default Debian docker.io 
# package doesn't work reliably. We need the official Docker CE CLI which puts
# the 'docker' command in PATH correctly for Dagger to find.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian bullseye stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.7.20-debian /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin
RUN curl -fsSL https://dl.dagger.io/dagger/install.sh | DAGGER_VERSION=0.18.16 BIN_DIR=/usr/local/bin sh

WORKDIR /app

COPY pyproject.toml uv.lock ./
ENV UV_COMPILE_BYTECODE=1
ENV UV_FROZEN=1
RUN uv venv && uv sync --no-dev && if [ -n "${OLLAMA_HOST:-}" ]; then uv sync --group ollama --no-dev; fi
# should be cacheable

COPY . /app

EXPOSE 8001
ENV PYTHONPATH=/app
ENTRYPOINT ["uv",  "run", "--no-dev", "server"]
