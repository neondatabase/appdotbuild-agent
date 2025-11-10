#!/bin/bash
set -e

# Docker template test script
# For Docker apps, we run tests before the Docker build
# Docker apps are typically built from dbx-sdk or trpc templates

# Try root-level test (works for both dbx-sdk and trpc)
if [ -f "package.json" ] && grep -q '"test"' package.json 2>/dev/null; then
    # Check if test files exist
    if [ -d "server/src" ]; then
        TEST_FILES=$(find server/src -name "*.test.ts" 2>/dev/null | wc -l)
        if [ "$TEST_FILES" -eq 0 ]; then
            echo "❌ Error: No test files found" >&2
            exit 1
        fi
    elif [ -d "backend/src" ]; then
        TEST_FILES=$(find backend/src -name "*.test.ts" 2>/dev/null | wc -l)
        if [ "$TEST_FILES" -eq 0 ]; then
            echo "❌ Error: No test files found" >&2
            exit 1
        fi
    else
        echo "❌ Error: No test files found" >&2
        exit 1
    fi

    # Run tests
    exec npm test
fi

echo "❌ Error: No test script found in package.json" >&2
exit 1
