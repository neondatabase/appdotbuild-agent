#!/bin/bash

# tRPC template stop script
# Cleans up npm processes and port 8000

# Kill processes on port 8000
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true

# Kill npm start processes
pkill -f "npm start" 2>/dev/null || true

# Kill tsx server processes (both server/index.ts and server/src/index.ts)
pkill -f "tsx server/index.ts" 2>/dev/null || true
pkill -f "tsx server/src/index.ts" 2>/dev/null || true
pkill -f "tsx.*server.*index" 2>/dev/null || true

exit 0
