#!/bin/bash
set -e

# Vite template typecheck script
# Runs tsc --noEmit

echo "Running type check..."

if [ -f "package.json" ]; then
    # Check if typecheck script exists
    if npm run --silent 2>/dev/null | grep -q "typecheck"; then
        npm run typecheck
    else
        # Fallback to direct tsc
        npx tsc --noEmit
    fi
else
    echo "❌ Error: No package.json found" >&2
    exit 1
fi

echo "✅ Type check passed"
