FROM python:3.12-slim AS prod

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.7.20-debian /uv /uvx /bin/
RUN curl -fsSL https://dl.dagger.io/dagger/install.sh | BIN_DIR=/usr/local/bin sh

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
