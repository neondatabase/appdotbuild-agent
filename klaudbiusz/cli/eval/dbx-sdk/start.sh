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

# Update .env file with container env vars (so Node's --env-file-if-exists uses correct values)
# This is needed because Node's --env-file-if-exists loads .env AFTER process.env
if [ -f ".env" ]; then
    # Create temp file with container env vars taking precedence
    cp .env .env.bak
    
    # Update DATABRICKS_APP_PORT if set in container env
    if [ -n "$DATABRICKS_APP_PORT" ]; then
        if grep -q "^DATABRICKS_APP_PORT=" .env; then
            sed -i "s/^DATABRICKS_APP_PORT=.*/DATABRICKS_APP_PORT=$DATABRICKS_APP_PORT/" .env
        else
            echo "DATABRICKS_APP_PORT=$DATABRICKS_APP_PORT" >> .env
        fi
    fi
    
    # Update other critical vars similarly
    # Note: Using @ as sed delimiter to handle URLs with // properly
    for var in DATABRICKS_HOST DATABRICKS_TOKEN DATABRICKS_WAREHOUSE_ID DATABRICKS_APP_NAME; do
        val="${!var}"
        if [ -n "$val" ]; then
            if grep -q "^${var}=" .env; then
                # Remove the line and append new value (safer than sed substitution with special chars)
                grep -v "^${var}=" .env > .env.tmp && mv .env.tmp .env
            fi
            echo "${var}=$val" >> .env
        fi
    done
fi

# Check required env vars
if [ -z "$DATABRICKS_HOST" ] || [ -z "$DATABRICKS_TOKEN" ]; then
    echo "❌ Error: DATABRICKS_HOST and DATABRICKS_TOKEN must be set" >&2
    exit 1
fi

# Set default port if not provided
DATABRICKS_APP_PORT="${DATABRICKS_APP_PORT:-8000}"

# Verify package.json exists
if [ ! -f "package.json" ]; then
    echo "❌ Error: No package.json found in root directory" >&2
    exit 1
fi

# Start the app in background (capture stdout/stderr for debugging)
npm start > /tmp/app_stdout.log 2> /tmp/app_stderr.log &
APP_PID=$!

# Wait for app to start (5 seconds for npm apps)
sleep 5

# Check if process is still running
if ! kill -0 $APP_PID 2>/dev/null; then
    echo "❌ Error: Process died during startup" >&2
    if [ -s /tmp/app_stderr.log ]; then
        echo "--- App stderr ---" >&2
        cat /tmp/app_stderr.log >&2
    fi
    if [ -s /tmp/app_stdout.log ]; then
        echo "--- App stdout (last 50 lines) ---" >&2
        tail -50 /tmp/app_stdout.log >&2
    fi
    echo "--- End of logs ---" >&2
    exit 1
fi

# Health check with retries (5 attempts, 3s timeout each, 2s apart)
# Accept any HTTP response (not just 2xx) since apps may return 401 before auth
for i in {1..5}; do
    # Try healthcheck endpoint first
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:${DATABRICKS_APP_PORT}/healthcheck 2>&1)
    if [ "$RESPONSE" != "000" ]; then
        echo "✅ App ready (HTTP $RESPONSE)" >&2
        exit 0
    fi

    # Fallback to root endpoint
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:${DATABRICKS_APP_PORT}/ 2>&1)
    if [ "$RESPONSE" != "000" ]; then
        echo "✅ App ready (HTTP $RESPONSE)" >&2
        exit 0
    fi

    # Wait before retry (except on last attempt)
    if [ $i -lt 5 ]; then
        sleep 2
    fi
done

# Failed to connect - show debug info
echo "❌ Error: App failed health check on port ${DATABRICKS_APP_PORT}" >&2
echo "--- Debug: checking if process is still alive ---" >&2
if kill -0 $APP_PID 2>/dev/null; then
    echo "Process $APP_PID is still running" >&2
else
    echo "Process $APP_PID has died" >&2
fi
echo "--- App stderr ---" >&2
cat /tmp/app_stderr.log 2>/dev/null >&2 || echo "(no stderr)" >&2
echo "--- App stdout (last 20 lines) ---" >&2
tail -20 /tmp/app_stdout.log 2>/dev/null >&2 || echo "(no stdout)" >&2
echo "--- End of debug ---" >&2
exit 1
