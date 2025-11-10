#!/bin/bash
set -e

# tRPC template start script
# Runs npm start from server/ directory

# Load .env file if it exists (optional - env vars passed from Python)
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
fi

# Check required env vars
if [ -z "$DATABRICKS_HOST" ] || [ -z "$DATABRICKS_TOKEN" ]; then
    echo "❌ Error: DATABRICKS_HOST and DATABRICKS_TOKEN must be set" >&2
    exit 1
fi

# Verify server directory and package.json exist
if [ ! -d "server" ]; then
    echo "❌ Error: No server/ directory found" >&2
    exit 1
fi

if [ ! -f "server/package.json" ]; then
    echo "❌ Error: No package.json found in server/ directory" >&2
    exit 1
fi

# Start the app from server directory
cd server && exec npm start
