#!/bin/bash
set -e

# MCP Mode - Full Evaluation Pipeline
# Archives previous run, cleans up, generates apps, runs evaluation

echo "=========================================="
echo "MCP Mode - Full Pipeline"
echo "=========================================="
echo ""

# Load environment variables from .env file if it exists
if [ -f .env ]; then
    echo "✅ Loading environment variables from .env"
    export $(grep -v '^#' .env | xargs)
fi

# Record start time
START_TIME=$(date +%s)
RUN_ID=$(date +%Y%m%d_%H%M%S)

# Check required environment variables
if [ -z "$DATABRICKS_HOST" ] || [ -z "$DATABRICKS_TOKEN" ] || [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ Error: Required environment variables not set:"
    echo "   DATABRICKS_HOST, DATABRICKS_TOKEN, ANTHROPIC_API_KEY"
    echo "   Set them via shell export or create a .env file"
    exit 1
fi

echo "📋 Run Configuration:"
echo "   Mode: MCP (TypeScript/tRPC)"
echo "   Run ID: $RUN_ID"
echo "   Date: $(date)"
echo ""

# Step 1: Archive previous run
echo "📦 Step 1/5: Archiving previous run..."
if [ -d "app" ] && [ "$(ls -A app 2>/dev/null)" ]; then
    ./cli/archive_evaluation.sh
    echo "✅ Previous run archived"
else
    echo "ℹ️  No previous run to archive"
fi
echo ""

# Step 2: Clean up
echo "🧹 Step 2/5: Cleaning up..."
./cli/cleanup_evaluation.sh
echo "✅ Cleanup complete"
echo ""

# Step 3: Generate apps (MCP mode - default)
echo "🤖 Step 3/5: Generating apps (MCP mode - TypeScript/tRPC)..."
GEN_START=$(date +%s)
uv run cli/bulk_run.py --n_jobs=-1
GEN_END=$(date +%s)
GEN_DURATION=$((GEN_END - GEN_START))
echo "✅ App generation complete (${GEN_DURATION}s)"
echo ""

# Step 4: Run evaluation (with agent-based metrics)
echo "📊 Step 4/5: Running evaluation (direct + agent-based metrics)..."
echo "   ⚠️  Note: Agent metrics may take 2-3 min per app"
EVAL_START=$(date +%s)
export EVAL_MODE="mcp"
uv run python3 evaluate_apps.py
EVAL_END=$(date +%s)
EVAL_DURATION=$((EVAL_END - EVAL_START))

# Add mode information to evaluation report
if [ -f evaluation_report.json ]; then
    python3 -c "
import json
with open('evaluation_report.json', 'r') as f:
    data = json.load(f)
if 'summary' not in data:
    data['summary'] = {}
data['summary']['mode'] = 'MCP (TypeScript/tRPC)'
with open('evaluation_report.json', 'w') as f:
    json.dump(data, f, indent=2)
"
fi

echo "✅ Evaluation complete (${EVAL_DURATION}s)"
echo ""

# Record run metadata
END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))

cat > run_metadata.json << EOF
{
  "run_id": "$RUN_ID",
  "mode": "mcp",
  "enable_mcp": true,
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "date_human": "$(date)",
  "duration_total_sec": $TOTAL_DURATION,
  "duration_generation_sec": $GEN_DURATION,
  "duration_evaluation_sec": $EVAL_DURATION,
  "environment": {
    "databricks_host": "$DATABRICKS_HOST",
    "os": "$(uname -s)",
    "hostname": "$(hostname)"
  },
  "parameters": {
    "n_jobs": -1,
    "wipe_db": false,
    "use_subagents": false,
    "stack": "TypeScript/tRPC"
  }
}
EOF

# Step 5: Generate HTML viewer
echo "🌐 Step 5/5: Generating HTML viewer..."
python3 cli/generate_html_viewer.py

echo "=========================================="
echo "✅ Pipeline Complete!"
echo "=========================================="
echo ""
echo "📊 Summary:"
echo "   Run ID: $RUN_ID"
echo "   Mode: MCP (TypeScript/tRPC)"
echo "   Total time: ${TOTAL_DURATION}s ($(($TOTAL_DURATION / 60))m $(($TOTAL_DURATION % 60))s)"
echo "   Generation: ${GEN_DURATION}s"
echo "   Evaluation: ${EVAL_DURATION}s"
echo ""
echo "📁 Outputs:"
echo "   - evaluation_report.json"
echo "   - EVALUATION_REPORT.md"
echo "   - run_metadata.json"
echo "   - evaluation_viewer.html"
echo ""
echo "🌐 View results:"
echo "   open evaluation_viewer.html"
echo ""
