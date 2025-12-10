#!/bin/bash

# Vite template stop script
# Kills any running node processes

pkill -f "vite preview" 2>/dev/null || true
pkill -f "node.*preview" 2>/dev/null || true

echo "✅ Stopped"
