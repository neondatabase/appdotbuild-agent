#!/bin/bash
set -e

# Docker template start script
# Runs Docker container with Databricks environment

# Get app name from current directory
APP_NAME=$(basename "$PWD")

# Container name can be overridden via env var
CONTAINER_NAME="${CONTAINER_NAME:-eval-${APP_NAME}-$(date +%s)}"

# Check if Docker image exists
if ! docker image inspect "eval-${APP_NAME}" >/dev/null 2>&1; then
    echo "❌ Error: Docker image eval-${APP_NAME} not found. Run docker build first." >&2
    exit 1
fi

# Prepare env file args if .env exists
ENV_FILE_ARGS=""
if [ -f "../.env" ]; then
    ENV_FILE_ARGS="--env-file ../.env"
elif [ -f "../../.env" ]; then
    ENV_FILE_ARGS="--env-file ../../.env"
fi

# Prepare Databricks env vars
ENV_VARS=()
for var in DATABRICKS_HOST DATABRICKS_TOKEN DATABRICKS_WAREHOUSE_ID; do
    if [ -n "${!var}" ]; then
        ENV_VARS+=("-e" "${var}=${!var}")
    fi
done

# Add OAuth credentials (with defaults for eval)
DATABRICKS_CLIENT_ID="${DATABRICKS_CLIENT_ID:-eval-mock-client-id}"
DATABRICKS_CLIENT_SECRET="${DATABRICKS_CLIENT_SECRET:-eval-mock-client-secret}"
DATABRICKS_APP_NAME="${DATABRICKS_APP_NAME:-${APP_NAME}}"
ENV_VARS+=("-e" "DATABRICKS_CLIENT_ID=${DATABRICKS_CLIENT_ID}")
ENV_VARS+=("-e" "DATABRICKS_CLIENT_SECRET=${DATABRICKS_CLIENT_SECRET}")
ENV_VARS+=("-e" "DATABRICKS_APP_NAME=${DATABRICKS_APP_NAME}")

# Add server plugin requirements
DATABRICKS_APP_PORT="${DATABRICKS_APP_PORT:-8000}"
FLASK_RUN_HOST="${FLASK_RUN_HOST:-0.0.0.0}"
ENV_VARS+=("-e" "DATABRICKS_APP_PORT=${DATABRICKS_APP_PORT}")
ENV_VARS+=("-e" "FLASK_RUN_HOST=${FLASK_RUN_HOST}")

# Run the container
exec docker run -d -p 8000:8000 \
    --name "${CONTAINER_NAME}" \
    ${ENV_FILE_ARGS} \
    "${ENV_VARS[@]}" \
    "eval-${APP_NAME}"
