#!/bin/bash
set -e

# DBX SDK template start script
# Runs npm start from root directory (backend/ structure)

# ===== PREREQUISITE CHECKS =====
# Check if required tools are installed
MISSING_TOOLS=()

if ! command -v npm &> /dev/null; then
    MISSING_TOOLS+=("npm")
fi

if ! command -v curl &> /dev/null; then
    MISSING_TOOLS+=("curl")
fi

# Check if tsx is available (either globally or via npx)
if ! command -v tsx &> /dev/null && ! command -v npx &> /dev/null; then
    MISSING_TOOLS+=("tsx or npx")
fi

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo "❌ Error: Missing required tools: ${MISSING_TOOLS[*]}" >&2
    echo "   Please install the missing tools and try again." >&2
    exit 2
fi
# ===== END PREREQUISITE CHECKS =====

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

# Start the app in background (redirect output to prevent Python subprocess hang)
npm start >/dev/null 2>&1 &
APP_PID=$!

# Wait for app to start (5 seconds for npm apps)
sleep 5

# Check if process is still running
if ! kill -0 $APP_PID 2>/dev/null; then
    echo "❌ Error: Process died during startup" >&2
    exit 1
fi

# Health check with retries (3 attempts, 2s timeout each, 1s apart)
for i in {1..3}; do
    # Try healthcheck endpoint first
    if curl -f -s --max-time 2 http://localhost:8000/healthcheck >/dev/null 2>&1; then
        echo "✅ App ready (healthcheck)" >&2
        exit 0
    fi

    # Fallback to root endpoint for npm apps
    if curl -f -s --max-time 2 http://localhost:8000/ >/dev/null 2>&1; then
        echo "✅ App ready (root)" >&2
        exit 0
    fi

    # Wait before retry (except on last attempt)
    if [ $i -lt 3 ]; then
        sleep 1
    fi
done

# Failed to connect
echo "❌ Error: App failed health check" >&2
exit 1
