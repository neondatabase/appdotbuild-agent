# edda_mcp

MCP server providing scaffolding, validation, and Databricks integration tools.

## Installation

```bash
cargo install --path .
```

Add to Claude Code:

```bash
claude mcp add --transport stdio edda -- edda_mcp
```

## Configuration

Global config: `~/.edda/config.json` (created automatically with defaults)

### CLI Flags

Two modes (mutually exclusive):

**1. Individual flags** (recommended):
```bash
edda_mcp --screenshot.port 8080 --screenshot.enabled true
edda_mcp --validation.command "npm test"
edda_mcp --with-deployment false
```

**2. JSON replacement**:
```bash
edda_mcp --json '{"with_deployment":false,"io_config":{"template":"Trpc"}}'
```

### Available Flags

See config.rs for full schema.

**Top-level:**
- `--with-deployment` (default: `true`)
- `--with-workspace-tools` (default: `false`)

**Template:**
- `--template Trpc` (use `--json` for custom templates)

**Validation:**
- `--validation.command "npm test"`
- `--validation.docker_image "node:20"`

**Screenshot:**
- `--screenshot.enabled true` (default: `true`)
- `--screenshot.url "/"` (default: `"/"`)
- `--screenshot.port 8080` (default: `8000`)
- `--screenshot.wait_time_ms 5000` (default: `30000`)

Priority: CLI flags > global config > defaults
