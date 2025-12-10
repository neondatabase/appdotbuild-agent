#!/bin/bash
# Don't use set -e

# DBX SDK template test script
echo "Running tests..." >&2

# Check if test script exists in package.json
if [ ! -f "package.json" ] || ! grep -q '"test"' package.json 2>/dev/null || grep -q '"test": *".*echo.*Error.*no test.*"' package.json 2>/dev/null; then
    echo "No tests configured - skipping" >&2
    exit 0
fi

# Check for EVAL_FAST_MODE env var (set by evaluation scripts)
if [ "$EVAL_FAST_MODE" = "true" ]; then
    # Fast mode: skip smoke tests, run only vitest unit tests
    echo "Fast mode: running unit tests only (skipping smoke tests)" >&2
    if npx vitest run --exclude '**/smoke*' --exclude '**/*.spec.ts' 2>&1; then
        echo "✅ Unit tests passed" >&2
        exit 0
    else
        echo "❌ Unit tests failed" >&2
        exit 1
    fi
else
    # Full mode: run all tests including smoke
    if npm test 2>&1; then
        echo "✅ Tests passed" >&2
        exit 0
    else
        echo "❌ Tests failed" >&2
        exit 1
    fi
fi
