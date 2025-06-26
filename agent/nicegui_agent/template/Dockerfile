FROM python:3.12-slim

# Environment variables
ENV NICEGUI_STORAGE_SECRET=${NICEGUI_STORAGE_SECRET:-STORAGE_SECRET}
ENV NICEGUI_PORT=${NICEGUI_PORT:-8000}

# Install uv and system dependencies
RUN pip install uv && \
    apt-get update && apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY . .

# Install dependencies with uv
RUN uv sync --no-dev

# Expose port
EXPOSE ${NICEGUI_PORT:-8000}

# Run the application with uv
CMD ["uv", "run", "python", "main.py", "--no-dev"]
