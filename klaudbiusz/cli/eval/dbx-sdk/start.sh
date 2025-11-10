#!/bin/bash
set -e

# DBX SDK template start script
# Runs npm start from root directory (backend/ structure)

# Load .env file if it exists (optional - env vars passed from Python)
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
fi

# Check required env vars
if [ -z "$DATABRICKS_HOST" ] || [ -z "$DATABRICKS_TOKEN" ]; then
    echo "❌ Error: DATABRICKS_HOST and DATABRICKS_TOKEN must be set" >&2
    exit 1
fi

# Verify package.json exists
if [ ! -f "package.json" ]; then
    echo "❌ Error: No package.json found in root directory" >&2
    exit 1
fi

# Start the app
exec npm start
