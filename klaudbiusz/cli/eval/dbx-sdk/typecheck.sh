#!/bin/bash
set -e

# DBX SDK template typecheck script
# Runs TypeScript type checking using npm run check or tsc directly

# Verify package.json exists
if [ ! -f "package.json" ]; then
    echo "❌ Error: No package.json found" >&2
    exit 1
fi

# Check if npm run check is available (standard for DBX SDK)
if grep -q '"check"' package.json 2>/dev/null; then
    exec npm run check
else
    # Fallback: run tsc directly
    exec npx tsc --noEmit --skipLibCheck
fi
