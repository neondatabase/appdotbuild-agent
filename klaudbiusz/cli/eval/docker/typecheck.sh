#!/bin/bash
set -e

# Docker template typecheck script
# For Docker apps, we check the source before the Docker build
# Docker apps are typically built from dbx-sdk or trpc templates

# Try root-level check first (dbx-sdk style)
if [ -f "package.json" ] && grep -q '"check"' package.json 2>/dev/null; then
    exec npm run check
fi

# Try direct tsc at root
if [ -f "tsconfig.json" ]; then
    exec npx tsc --noEmit --skipLibCheck
fi

# Try server directory (trpc style)
if [ -d "server" ] && [ -f "server/tsconfig.json" ]; then
    echo "Checking server types..." >&2
    cd server && npx tsc --noEmit --skipLibCheck && cd ..

    # Also check client if exists
    if [ -d "../client" ] && [ -f "../client/tsconfig.json" ]; then
        cd ../client && npx tsc --noEmit --skipLibCheck
    fi
    exit 0
fi

echo "❌ Error: Could not determine type checking strategy" >&2
exit 1
