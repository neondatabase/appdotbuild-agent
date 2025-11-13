#!/bin/bash
set -e

# tRPC template: Install dependencies
# This script handles dependency installation for tRPC monorepo structure

echo "Installing dependencies..." >&2

# Check if root package.json has install:all script
if [ -f "package.json" ] && grep -q '"install:all"' package.json 2>/dev/null; then
    echo "Running npm run install:all..." >&2
    npm run install:all
else
    # Install server dependencies
    if [ -d "server" ] && [ -f "server/package.json" ]; then
        echo "Installing server dependencies..." >&2
        cd server && npm install && cd ..
    fi

    # Install client dependencies (try both client/ and frontend/)
    if [ -d "client" ] && [ -f "client/package.json" ]; then
        echo "Installing client dependencies..." >&2
        cd client && npm install && cd ..
    elif [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
        echo "Installing frontend dependencies..." >&2
        cd frontend && npm install && cd ..
    fi
fi

echo "✅ Dependencies installed" >&2
