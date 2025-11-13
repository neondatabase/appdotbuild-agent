#!/bin/bash
set -e

# Docker template: Build the application
# For Docker, we use docker build command

echo "Building Docker image..." >&2

if [ ! -f "Dockerfile" ]; then
    echo "⚠️  No Dockerfile found" >&2
    exit 1
fi

# Get app name from DATABRICKS_APP_NAME env var or use default
APP_NAME="${DATABRICKS_APP_NAME:-app}"

docker build -t "eval-${APP_NAME}" .
echo "✅ Docker image built successfully" >&2
