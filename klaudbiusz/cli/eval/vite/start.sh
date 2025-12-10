#!/bin/bash
set -e

# Vite template start script
# Runs npm run preview (serves built app)

if [ ! -f "package.json" ]; then
    echo "❌ Error: No package.json found" >&2
    exit 1
fi

# Set default port if not provided
PORT="${DATABRICKS_APP_PORT:-4173}"

# Start the preview server in background
npm run preview -- --port $PORT > /tmp/app_stdout.log 2> /tmp/app_stderr.log &
APP_PID=$!

# Give server a moment to start
sleep 1

# Poll until app responds or timeout (max 10 seconds, check every 0.5s)
MAX_WAIT=20
for i in $(seq 1 $MAX_WAIT); do
    # Check if process died
    if ! kill -0 $APP_PID 2>/dev/null; then
        echo "❌ Error: Process died during startup" >&2
        cat /tmp/app_stderr.log >&2 2>/dev/null || true
        exit 1
    fi

    # Try to connect
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 1 http://localhost:${PORT}/ 2>/dev/null || true)
    if [ "$RESPONSE" != "000" ] && [ -n "$RESPONSE" ]; then
        echo "✅ App ready (HTTP $RESPONSE)" >&2
        exit 0
    fi

    sleep 0.5
done

echo "❌ Error: App failed to start within 10 seconds" >&2
cat /tmp/app_stderr.log >&2 2>/dev/null || true
exit 1
