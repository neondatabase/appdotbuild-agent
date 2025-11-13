#!/bin/bash
set -e

# tRPC template: Build the application
# For tRPC, we build the client (React frontend)

echo "Building application..." >&2

# Build client if it exists
if [ -d "client" ] && [ -f "client/package.json" ]; then
    if grep -q '"build"' client/package.json 2>/dev/null; then
        echo "Building client..." >&2
        cd client && npm run build && cd ..
        echo "✅ Client built successfully" >&2
    else
        echo "⚠️  No build script found in client/package.json" >&2
    fi
elif [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    if grep -q '"build"' frontend/package.json 2>/dev/null; then
        echo "Building frontend..." >&2
        cd frontend && npm run build && cd ..
        echo "✅ Frontend built successfully" >&2
    else
        echo "⚠️  No build script found in frontend/package.json" >&2
    fi
else
    # Try root-level build
    if [ -f "package.json" ] && grep -q '"build"' package.json 2>/dev/null; then
        echo "Building from root..." >&2
        npm run build
        echo "✅ Build successful" >&2
    else
        echo "⚠️  No build script found" >&2
    fi
fi
