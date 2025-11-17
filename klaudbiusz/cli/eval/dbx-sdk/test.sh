#!/bin/bash
# Don't use set -e

# DBX SDK template test script
echo "Running tests..." >&2

# Check if test script exists in package.json
if [ -f "package.json" ] && grep -q '"test"' package.json 2>/dev/null && ! grep -q '"test": *".*echo.*Error.*no test.*"' package.json 2>/dev/null; then
    if npm test 2>&1; then
        echo "✅ Tests passed" >&2
        exit 0
    else
        echo "❌ Tests failed" >&2
        exit 1
    fi
else
    echo "No tests configured - skipping" >&2
    exit 0
fi
