# klaudbiusz Claude Code Plugin

Production-ready data application generator for Claude Code.

## What This Is

This plugin packages the **dabgent-mcp** MCP server for distribution via Claude Code. It provides:

- **MCP Tools** - `scaffold_data_app`, `validate_data_app`, and other app generation tools
- **Specialized Subagent** - klaudbiusz agent with workflow expertise
- **Event Sourcing Architecture** - Full auditability and replay capabilities

## Architecture

klaudbiusz serves dual purposes:
1. **CLI wrapper** (main.py) - Development/debugging with full DB logging
2. **Claude Code plugin** (.claude-plugin/) - Distribution to users

Both invoke the same `dabgent-mcp` MCP server:

```
agent/
  klaudbiusz/
    main.py            # CLI with DB logging (for debugging)
    .claude-plugin/    # Plugin manifest (for distribution)
  dabgent/
    dabgent_mcp/       # Core MCP server (used by both)
```

**Use CLI for:** Development, debugging, full logging/metrics
**Use plugin for:** End users, Claude Code integration

## Installation

### Local Development

1. **Add local marketplace:**

From Claude Code (use absolute path):
```
/plugin marketplace add /Users/arseni.kravchenko/dev/agent/klaudbiusz
```

Or relative path (if you're in the agent directory):
```
/plugin marketplace add ./klaudbiusz
```

2. **Install plugin:**
```
/plugin install klaudbiusz
```

3. **Restart Claude Code** (required for plugin to load)

### Verification

Check MCP server is loaded:
```
/mcp list
```

You should see `klaudbiusz` in the list.

## Testing

1. **Create test directory:**
```bash
mkdir -p /tmp/dabgent-test
cd /tmp/dabgent-test
```

2. **In Claude Code, try:**
```
Create a simple dashboard application that displays user statistics
```

3. **Verify the appbuild agent is invoked:**
- Check for "Using subagent: appbuild" message
- `scaffold_data_app` should scaffold the project in `./app/`
- `validate_data_app` should run at the end
- Tests should be added automatically

4. **Or explicitly invoke the agent:**
```
@agent-klaudbiusz:appbuild
```

## Debugging

If the plugin doesn't work:

1. **Check MCP server logs:**
```bash
# MCP server logs to stderr by default
# Check Claude Code's MCP debug output
```

2. **Launch Claude Code with debug flag:**
```bash
claude --mcp-debug
```

3. **Fall back to klaudbiusz CLI:**
```bash
cd /Users/arseni.kravchenko/dev/agent/klaudbiusz
uv run python main.py "Create a simple dashboard"
```

This provides full DB logging and easier debugging.

## Subagents

The plugin includes two specialized subagents:

### appbuild
Specializes in data application generation:
- **Automatic invocation** - Triggered when user requests apps/dashboards
- **Explicit invocation** - Use `@agent-klaudbiusz:appbuild` to invoke directly
- **Workflow expertise** - Knows to use `scaffold_data_app` → implement → `validate_data_app`
- **Best practices** - Always adds tests, biases towards backend, validates before completion

### dataresearch
Specializes in Databricks data exploration:
- **Explicit invocation** - Use `@agent-klaudbiusz:dataresearch` or `/databricks-research` command
- **Data expertise** - Explores schemas, executes SQL, fetches sample data
- **Delegation pattern** - appbuild agent delegates to dataresearch for Databricks work

Both agents appear in `/agents` list when plugin is loaded.

## Custom Commands

### /databricks-research
Use this command when working with Databricks data to inject proper delegation instructions.
This ensures the appbuild agent delegates to dataresearch instead of using Databricks tools directly.

## MCP Server Details

**Command:** `cargo run --manifest-path ${CLAUDE_PLUGIN_ROOT}/../../dabgent/dabgent_mcp/Cargo.toml`

**Transport:** stdio

**Dependencies:**
- Rust toolchain (cargo must be in PATH)
- dabgent workspace at `../dabgent/`

## Development Workflow

1. **Make changes to dabgent-mcp** in `../dabgent/dabgent_mcp/src/`
2. **Test via klaudbiusz CLI** (faster iteration)
3. **Once working, test via plugin:**
   ```
   /plugin uninstall klaudbiusz
   /plugin install klaudbiusz
   ```
4. **Restart Claude Code** to reload plugin

## Distribution (Future)

When ready for customers:

1. Build `dabgent_mcp` as static binary
2. Update `plugin.json` to point to binary instead of `cargo run`
3. Package plugin directory
4. Distribute via marketplace or direct download

## Troubleshooting

**Plugin not found:**
- Verify marketplace path is correct
- Check `.claude-plugin/plugin.json` exists

**MCP server fails to start:**
- Verify cargo is in PATH: `which cargo`
- Test MCP server directly: `cd ../dabgent/dabgent_mcp && cargo run`
- Check `../dabgent/dabgent_mcp/Cargo.toml` exists

**Tools not working:**
- Verify MCP server is loaded: `/mcp list`
- Check Claude Code logs for MCP errors
- Try with `--mcp-debug` flag

**Agent not appearing:**
- Verify agent loaded: `/agents` should show appbuild
- Check `agents/klaudbiusz.md` exists in plugin directory
- Restart Claude Code after plugin installation

**Need full debugging:**
- Switch to klaudbiusz CLI for full conversation logging to Postgres
- Custom metrics and instrumentation available in CLI mode
