#!/bin/bash
set -e

# Docker template: Install dependencies
# This script handles various project structures (trpc, dbx-sdk, or custom)

echo "Installing dependencies..." >&2

# Check if root package.json has install:all script (trpc style)
if [ -f "package.json" ] && grep -q '"install:all"' package.json 2>/dev/null; then
    echo "Running npm run install:all..." >&2
    npm run install:all
elif [ -f "package.json" ]; then
    # Root-level app (dbx-sdk style)
    echo "Installing root dependencies..." >&2
    npm install
else
    # Install server/client separately if they exist
    if [ -d "server" ] && [ -f "server/package.json" ]; then
        echo "Installing server dependencies..." >&2
        cd server && npm install && cd ..
    fi

    if [ -d "client" ] && [ -f "client/package.json" ]; then
        echo "Installing client dependencies..." >&2
        cd client && npm install && cd ..
    elif [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
        echo "Installing frontend dependencies..." >&2
        cd frontend && npm install && cd ..
    fi
fi

echo "✅ Dependencies installed" >&2
