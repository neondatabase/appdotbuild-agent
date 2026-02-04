FROM python:3.12-slim

# install system dependencies in single layer (includes playwright browser deps)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends curl unzip git && \
    curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libasound2 libatspi2.0-0 libcairo2 libpango-1.0-0

# install bun for opencode backend (copy binary to system path)
RUN curl -fsSL https://bun.sh/install | bash && \
    cp /root/.bun/bin/bun /usr/local/bin/bun && \
    rm -rf /root/.bun

# install opencode CLI (copy binary to system path)
# pin version to avoid flaky version API
RUN curl -fsSL https://opencode.ai/install | bash -s -- --version 1.0.180 && \
    cp /root/.opencode/bin/opencode /usr/local/bin/opencode && \
    rm -rf /root/.opencode

# install npm packages with cache mount
RUN --mount=type=cache,target=/root/.npm \
    npm install -g @anthropic-ai/claude-code

# pre-populate npm cache with common packages used in generated apps
# install to temp dir to populate cache, then delete to save image space
RUN --mount=type=cache,target=/root/.npm \
    mkdir -p /tmp/cache-warmer && cd /tmp/cache-warmer && \
    npm install --no-save \
        @radix-ui/react-accordion@^1.2.0 \
        @radix-ui/react-dialog@^1.1.0 \
        @radix-ui/react-dropdown-menu@^2.1.0 \
        @radix-ui/react-select@^2.2.0 \
        @databricks/sdk-experimental@^0.14.0 \
        react@^18.0.0 \
        react-dom@^18.0.0 && \
    cd / && rm -rf /tmp/cache-warmer

WORKDIR /workspace

# install uv for package management
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# install dependencies with uv cache mount (cached until pyproject.toml changes)
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    mkdir -p cli && touch cli/__init__.py && \
    uv pip install --system -e . && \
    rm -rf cli

# copy only generation-related source code (exclude evaluation to prevent reward hacking)
COPY cli/__init__.py ./cli/
COPY cli/trajectory.py ./cli/
COPY cli/generation/ ./cli/generation/
COPY cli/utils/ ./cli/utils/
COPY cli/generation_opencode/ ./cli/generation_opencode/

# install opencode generation dependencies (bun install)
RUN --mount=type=cache,target=/root/.bun/install/cache \
    cd cli/generation_opencode && bun install

# create non-root user (claude agent sdk requires non-root for security)
# pre-create .local directories for opencode (share for auth, state for runtime)
RUN useradd -m -s /bin/bash klaudbiusz && \
    mkdir -p /home/klaudbiusz/.local/share/opencode /home/klaudbiusz/.local/state && \
    chown -R klaudbiusz:klaudbiusz /workspace /home/klaudbiusz/.local

USER klaudbiusz

# install playwright and chromium as klaudbiusz user (needs write access to ~/.cache)
# playwright browsers are ~200MB, pre-installing avoids download in every generation
# install to temp dir to trigger browser download, then delete node_modules
RUN --mount=type=cache,target=/home/klaudbiusz/.npm,uid=1000,gid=1000 \
    mkdir -p /tmp/playwright-warmer && cd /tmp/playwright-warmer && \
    npm install --no-save @playwright/test@^1.57.0 && \
    npx playwright install chromium && \
    cd / && rm -rf /tmp/playwright-warmer

# set working directory for app generation
ENV APP_OUTPUT_DIR=/workspace/app
