#!/bin/bash
set -e

# tRPC template test script
# Runs tests using root-level npm test command

# Check if package.json exists
if [ ! -f "package.json" ]; then
    echo "❌ Error: No package.json found" >&2
    exit 1
fi

# Check if test script exists
if ! grep -q '"test"' package.json 2>/dev/null; then
    echo "❌ Error: No test script in package.json" >&2
    exit 1
fi

# Check if test files exist in server/src
if [ -d "server/src" ]; then
    TEST_FILES=$(find server/src -name "*.test.ts" 2>/dev/null | wc -l)
    if [ "$TEST_FILES" -eq 0 ]; then
        echo "❌ Error: No test files found in server/src" >&2
        exit 1
    fi
else
    echo "❌ Error: No server/src directory found" >&2
    exit 1
fi

# Run tests (output goes to stdout/stderr for coverage parsing)
exec npm test
