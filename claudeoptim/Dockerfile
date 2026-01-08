FROM python:3.12-slim-trixie

# Install system dependencies with apt cache mount
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends curl unzip git nodejs npm

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# UV environment configuration
ENV UV_NO_DEV=1
ENV UV_SYSTEM_PYTHON=1
ENV UV_LINK_MODE=copy

# Install sbclaude as a module with uv cache mount
WORKDIR /tmp/build
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install .

# Install claude code with npm cache mount
RUN --mount=type=cache,target=/root/.npm \
    npm install -g @anthropic-ai/claude-code

# Clean workdir
WORKDIR /app

# Create non-root user for claude code
RUN useradd -m -s /bin/bash sbclaude && \
    chown -R sbclaude:sbclaude /app

USER sbclaude

CMD ["python", "-m", "sbclaude.server"]
