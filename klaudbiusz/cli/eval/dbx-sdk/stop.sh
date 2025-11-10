#!/bin/bash

# DBX SDK template stop script
# Cleans up npm processes and port 8000

# Kill processes on port 8000
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true

# Kill npm start processes
pkill -f "npm start" 2>/dev/null || true

# Kill tsx backend/index.ts processes
pkill -f "tsx backend/index.ts" 2>/dev/null || true
pkill -f "tsx.*backend.*index" 2>/dev/null || true

exit 0
