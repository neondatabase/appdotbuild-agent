#!/bin/bash
set -e

# Vite template test script
# Runs npm test

echo "Running tests..."

if [ ! -f "package.json" ]; then
    echo "❌ Error: No package.json found" >&2
    exit 1
fi

# Check if test script exists
if npm run --silent 2>/dev/null | grep -q "test"; then
    npm test -- --run 2>&1 || npm test 2>&1
else
    echo "⚠️ No test script found, skipping"
    exit 0
fi

echo "✅ Tests passed"
