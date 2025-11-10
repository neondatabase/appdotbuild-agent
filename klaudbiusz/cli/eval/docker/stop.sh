#!/bin/bash

# Docker template stop script
# Stops and removes Docker containers

APP_NAME=$(basename "$PWD")

# Stop docker compose if present
if [ -f "docker-compose.yml" ] || [ -f "docker-compose.yaml" ]; then
    docker compose down 2>/dev/null || true
fi

# Stop and remove container with app name
docker stop "$APP_NAME" 2>/dev/null || true
docker rm "$APP_NAME" 2>/dev/null || true

# Stop any eval-* or test-* containers for this app
for container in $(docker ps -aq --filter "name=eval-${APP_NAME}" --filter "name=test-${APP_NAME}" 2>/dev/null); do
    docker stop "$container" 2>/dev/null || true
    docker rm "$container" 2>/dev/null || true
done

# Also clean up any containers using the eval image
for container in $(docker ps -aq --filter "ancestor=eval-${APP_NAME}" 2>/dev/null); do
    docker stop "$container" 2>/dev/null || true
    docker rm "$container" 2>/dev/null || true
done

exit 0
