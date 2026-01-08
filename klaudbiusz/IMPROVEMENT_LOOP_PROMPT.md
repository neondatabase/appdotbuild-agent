# Databricks App Generator Improvement Loop

You are running an improvement loop for the Databricks app generator. The system uses Claude Agent SDK with a Databricks CLI MCP server to generate data applications.

## Current Setup

- **This Repo:** Test harness for bulk generation and evaluation
- **CLI Repo:** Databricks CLI with MCP server (sibling directory `../cli` or set `$CLI_REPO`)
- **MCP Binary:** Linux ARM64 binary for Dagger containers

## Quick Commands

### Rebuild CLI (after changes)
```bash
cd $CLI_REPO && GOOS=linux GOARCH=arm64 go build -o cli-linux-arm64 .
```

### Test Single App (quick iteration)
```bash
rm -rf app/*
uv run -m cli.generation.bulk_run \
  --mcp_binary=$CLI_REPO/cli-linux-arm64 \
  --mcp_args='["experimental", "apps-mcp"]' \
  --max_concurrency=1 \
  --limit=1
```

### Full Bulk Generation (20 apps)
```bash
rm -rf app/*
uv run -m cli.generation.bulk_run \
  --mcp_binary=$CLI_REPO/cli-linux-arm64 \
  --mcp_args='["experimental", "apps-mcp"]' \
  --max_concurrency=10
```

### Run Evaluations
```bash
uv run python cli/evaluation/evaluate_all.py --dir app -j 4
```

## Improvement Loop Process

### Step 1: Run Bulk Generation
Use the quick commands above. Start with `--limit=1` for fast iteration.

### Step 2: Run Evaluations
```bash
uv run python cli/evaluation/evaluate_all.py --dir app -j 4
```

### Step 3: Analyze Results
- Check `cli/app-eval/EVALUATION_REPORT.md` for metrics
- Key metrics: Build Success, Runtime Success, Type Safety, DB Connectivity
- Check `app/logs/*.log` for tool call patterns

### Step 4: Diagnose Issues
Look for these patterns in logs:
```bash
# Check if MCP tools are called
grep -E "mcp__|databricks_discover|invoke_databricks" app/logs/*.log

# Check if init-template is used
grep "init-template" app/logs/*.log

# Check auth errors
grep -i "auth\|token\|refresh" app/logs/*.log

# Check tool errors
grep "Tool error" app/logs/*.log
```

### Step 5: Make Fixes

**CLI MCP Fixes** (preferred - in `$CLI_REPO`):
- Tool descriptions: `experimental/apps-mcp/lib/providers/clitools/provider.go`
- Flow template: `experimental/apps-mcp/lib/prompts/flow.tmpl`
- After changes: `cd $CLI_REPO && GOOS=linux GOARCH=arm64 go build -o cli-linux-arm64 .`

**Agent Prompt Fixes** (minimal - in this repo):
- Base instructions: `cli/generation/codegen.py` (look for `base_instructions`)
- Subagent restrictions: `cli/generation/codegen.py` (look for `agents = {}`)

### Step 6: Repeat
After fixes, go back to Step 1 and run another iteration.

## Known Issues & Fixes

1. **Auth Error:** Databricks OAuth token expires. Fix: `databricks auth login --host https://your-workspace.databricks.com`

2. **SDK Shutdown Crash:** Claude Agent SDK crashes during MCP server shutdown (known bug). Fixed by:
   - CLI: Graceful signal handling in `apps_mcp.go` (PR #4227)
   - Harness: `container_runner.py` exits 0 if app was built despite SDK error

3. **Bash Circumvention:** Fixed - Bash subagent restricted in `codegen.py` `agents` dict.

## Success Criteria

- 80%+ Build Success rate
- 70%+ Runtime Success rate
- Apps use proper Databricks bundle structure (databricks.yml present)
- MCP tools called: `databricks_discover` first, then `invoke_databricks_cli init-template`

## Key Files Reference

| File | Purpose |
|------|---------|
| `cli/generation/codegen.py` | Agent configuration, base_instructions, disallowed_tools |
| `cli/generation/bulk_run.py` | Bulk generation runner |
| `cli/evaluation/evaluate_all.py` | Evaluation runner |
| `cli/app-eval/EVALUATION_REPORT.md` | Latest evaluation results |
| `$CLI_REPO/experimental/apps-mcp/lib/providers/clitools/provider.go` | MCP tool definitions |
| `$CLI_REPO/experimental/apps-mcp/lib/prompts/flow.tmpl` | Workflow guidance template |
