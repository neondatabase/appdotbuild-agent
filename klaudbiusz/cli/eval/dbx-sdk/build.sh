#!/bin/bash
# Don't use set -e - handle errors gracefully

# DBX SDK template: Build the application
# For DBX SDK, we build from root package.json

echo "Building application..." >&2

if [ ! -f "package.json" ]; then
    echo "❌ No package.json found" >&2
    exit 1
fi

if ! grep -q '"build"' package.json 2>/dev/null; then
    echo "⚠️  No build script found in package.json - skipping" >&2
    exit 0
fi

echo "Building from root..." >&2
if npm run build 2>&1; then
    echo "✅ Build successful" >&2
    exit 0
else
    echo "❌ Build failed" >&2
    exit 1
fi
