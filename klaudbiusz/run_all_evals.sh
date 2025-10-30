#!/bin/bash
set -e

# Master script to run ALL evaluation modes sequentially
# This ensures complete testing of both Vanilla SDK and MCP modes

echo "================================================================"
echo "Master Evaluation Runner - All Modes"
echo "================================================================"
echo ""
echo "This will run evaluations in sequence:"
echo "  1. Vanilla SDK mode (Streamlit apps)"
echo "  2. MCP mode (TypeScript/tRPC apps)"
echo ""
echo "⏱️  Expected total time: ~60-90 minutes"
echo "================================================================"
echo ""

# Check for .env file
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "   Please create .env with required environment variables:"
    echo "   - ANTHROPIC_API_KEY"
    echo "   - DATABRICKS_HOST"
    echo "   - DATABRICKS_TOKEN"
    exit 1
fi

# Load environment
export $(grep -v '^#' .env | xargs)

# Verify required environment variables
if [ -z "$ANTHROPIC_API_KEY" ] || [ -z "$DATABRICKS_HOST" ] || [ -z "$DATABRICKS_TOKEN" ]; then
    echo "❌ Error: Required environment variables not set in .env"
    exit 1
fi

echo "✅ Environment loaded from .env"
echo ""

# Record start time
TOTAL_START=$(date +%s)

# Create results directory for this run
RUN_ID=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="results/${RUN_ID}"
mkdir -p "$RESULTS_DIR"

echo "📁 Results will be saved to: $RESULTS_DIR"
echo ""

# ============================================================
# Part 1: Vanilla SDK Mode
# ============================================================
echo "================================================================"
echo "PART 1/2: Vanilla SDK Mode (Streamlit)"
echo "================================================================"
echo ""

VANILLA_START=$(date +%s)

./run_vanilla_eval.sh 2>&1 | tee "$RESULTS_DIR/vanilla_eval.log"

VANILLA_END=$(date +%s)
VANILLA_DURATION=$((VANILLA_END - VANILLA_START))

# Archive vanilla results
if [ -f evaluation_report.json ]; then
    cp evaluation_report.json "$RESULTS_DIR/vanilla_report.json"
fi
if [ -f EVALUATION_REPORT.md ]; then
    cp EVALUATION_REPORT.md "$RESULTS_DIR/VANILLA_REPORT.md"
fi
if [ -f evaluation_viewer.html ]; then
    cp evaluation_viewer.html "$RESULTS_DIR/vanilla_viewer.html"
fi

echo ""
echo "✅ Vanilla SDK evaluation complete (${VANILLA_DURATION}s)"
echo ""
echo "================================================================"
echo "PART 2/2: MCP Mode (TypeScript/tRPC)"
echo "================================================================"
echo ""

MCP_START=$(date +%s)

./run_mcp_eval.sh 2>&1 | tee "$RESULTS_DIR/mcp_eval.log"

MCP_END=$(date +%s)
MCP_DURATION=$((MCP_END - MCP_START))

# Archive MCP results
if [ -f evaluation_report.json ]; then
    cp evaluation_report.json "$RESULTS_DIR/mcp_report.json"
fi
if [ -f EVALUATION_REPORT.md ]; then
    cp EVALUATION_REPORT.md "$RESULTS_DIR/MCP_REPORT.md"
fi
if [ -f evaluation_viewer.html ]; then
    cp evaluation_viewer.html "$RESULTS_DIR/mcp_viewer.html"
fi

echo ""
echo "✅ MCP evaluation complete (${MCP_DURATION}s)"
echo ""

# ============================================================
# Summary
# ============================================================
TOTAL_END=$(date +%s)
TOTAL_DURATION=$((TOTAL_END - TOTAL_START))

cat > "$RESULTS_DIR/run_summary.json" << EOFSUM
{
  "run_id": "$RUN_ID",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "date_human": "$(date)",
  "duration_total_sec": $TOTAL_DURATION,
  "duration_vanilla_sec": $VANILLA_DURATION,
  "duration_mcp_sec": $MCP_DURATION,
  "modes": ["vanilla_sdk", "mcp"],
  "results_directory": "$RESULTS_DIR",
  "environment": {
    "os": "$(uname -s)",
    "hostname": "$(hostname)"
  }
}
EOFSUM

echo "================================================================"
echo "✅ ALL EVALUATIONS COMPLETE!"
echo "================================================================"
echo ""
echo "📊 Summary:"
echo "   Run ID: $RUN_ID"
echo "   Total time: ${TOTAL_DURATION}s (~$(($TOTAL_DURATION / 60))m)"
echo "   Vanilla SDK: ${VANILLA_DURATION}s (~$(($VANILLA_DURATION / 60))m)"
echo "   MCP mode: ${MCP_DURATION}s (~$(($MCP_DURATION / 60))m)"
echo ""
echo "📁 All results saved to:"
echo "   $RESULTS_DIR/"
echo "   ├── vanilla_report.json"
echo "   ├── vanilla_viewer.html"
echo "   ├── mcp_report.json"
echo "   ├── mcp_viewer.html"
echo "   └── run_summary.json"
echo ""
echo "🌐 View results:"
echo "   open $RESULTS_DIR/vanilla_viewer.html"
echo "   open $RESULTS_DIR/mcp_viewer.html"
echo ""
