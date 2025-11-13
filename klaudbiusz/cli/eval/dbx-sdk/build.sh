#!/bin/bash
set -e

# DBX SDK template: Build the application
# For DBX SDK, we build from root package.json

echo "Building application..." >&2

if [ -f "package.json" ]; then
    if grep -q '"build"' package.json 2>/dev/null; then
        echo "Building from root..." >&2
        npm run build
        echo "✅ Build successful" >&2
    else
        echo "⚠️  No build script found in package.json" >&2
    fi
else
    echo "⚠️  No package.json found" >&2
fi
