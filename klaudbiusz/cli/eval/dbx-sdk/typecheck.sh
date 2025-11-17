#!/bin/bash
# Don't use set -e

# DBX SDK template typecheck script
# Runs TypeScript type checking using npm run check or tsc directly

echo "Running type check..." >&2

# Verify package.json exists
if [ ! -f "package.json" ]; then
    echo "❌ No package.json found" >&2
    exit 1
fi

# Check if npm run check is available (standard for DBX SDK)
if grep -q '"check"' package.json 2>/dev/null; then
    if npm run check 2>&1 >/dev/null; then
        echo "✅ Type check passed" >&2
        exit 0
    else
        echo "❌ Type check failed" >&2
        exit 1
    fi
else
    # Fallback: run tsc directly
    if npx tsc --noEmit --skipLibCheck 2>&1 >/dev/null; then
        echo "✅ Type check passed" >&2
        exit 0
    else
        echo "❌ Type check failed" >&2
        exit 1
    fi
fi
