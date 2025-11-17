#!/bin/bash
# Don't use set -e

# DBX SDK template: Install dependencies
# This template has a single root package.json

echo "Installing dependencies..." >&2

if [ ! -f "package.json" ]; then
    echo "❌ No package.json found" >&2
    exit 1
fi

if npm install 2>&1; then
    echo "✅ Dependencies installed" >&2
    exit 0
else
    echo "❌ Dependency installation failed" >&2
    exit 1
fi
