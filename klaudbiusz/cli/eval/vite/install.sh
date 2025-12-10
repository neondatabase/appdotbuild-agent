#!/bin/bash
set -e

# Vite template install script
# Installs npm dependencies from root package.json

echo "Installing dependencies..."

if [ ! -f "package.json" ]; then
    echo "❌ Error: No package.json found" >&2
    exit 1
fi

npm install --legacy-peer-deps

echo "✅ Dependencies installed"
