#!/bin/bash
set -e

# DBX SDK template: Install dependencies
# This template has a single root package.json

echo "Installing dependencies..." >&2

if [ -f "package.json" ]; then
    npm install
    echo "✅ Dependencies installed" >&2
else
    echo "⚠️  No package.json found" >&2
    exit 1
fi
