#!/bin/bash
set -e

# Vite template build script
# Runs npm run build

echo "Building application..."

if [ ! -f "package.json" ]; then
    echo "❌ Error: No package.json found" >&2
    exit 1
fi

npm run build

echo "✅ Build successful"
