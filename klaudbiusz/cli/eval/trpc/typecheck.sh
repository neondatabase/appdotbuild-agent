#!/bin/bash
set -e

# tRPC template typecheck script
# Runs TypeScript type checking separately for server/ and client/

# Check server directory
if [ -d "server" ] && [ -f "server/tsconfig.json" ]; then
    echo "Checking server types..." >&2
    cd server && npx tsc --noEmit --skipLibCheck
    cd ..
else
    echo "⚠️  Warning: No server/tsconfig.json found" >&2
fi

# Check client directory (try both client/ and frontend/)
if [ -d "client" ] && [ -f "client/tsconfig.json" ]; then
    echo "Checking client types..." >&2
    cd client && npx tsc --noEmit --skipLibCheck
elif [ -d "frontend" ] && [ -f "frontend/tsconfig.json" ]; then
    echo "Checking frontend types..." >&2
    cd frontend && npx tsc --noEmit --skipLibCheck
else
    echo "⚠️  Warning: No client/tsconfig.json or frontend/tsconfig.json found" >&2
fi

echo "✅ Type checking completed" >&2
exit 0
