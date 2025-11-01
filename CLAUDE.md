# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This monorepo contains:
- **edda/** - Rust-based event-sourced AI agent orchestration system (primary focus)
- **klaudbiusz/** - Python wrapper around Claude Agent SDK using edda MCP (secondary focus)
- **agent/** - Legacy Python implementation (no longer maintained, mentioned for context only)

Active development happens in **edda/** with occasional work in **klaudbiusz/**.

## Edda - Event-Sourced Agent Orchestration (Rust)

### Architecture

Edda is a modular event-sourced AI agent system primarily exposed as an **MCP server** for existing agents (like Claude Code). Originally designed as a standalone agent, it was redesigned to focus on MCP integration. The standalone agent (edda_agent/edda_cli) is in early stage and postponed.

Core capabilities:
- **Event-Sourced Architecture**: Full event history with aggregate state reconstruction (edda_mq - stable)
- **Multi-Agent Coordination**: Link agents with bidirectional communication via `Link` trait
- **Pluggable LLM Support**: Provider-agnostic (Anthropic, Gemini via Rig)
- **Sandboxed Execution**: Dagger-based containerized tool execution
- **Type-Safe Event Handling**: Strongly-typed events, commands, responses

### Workspace Structure

| Crate | Purpose | Status |
|-------|---------|--------|
| **edda_mcp** | MCP server exposing scaffolding + Databricks tools | **Active (primary focus)** |
| **edda_sandbox** | Dagger-based containerized tool execution | **Active** |
| **edda_integrations** | External service integrations (Databricks, Google Sheets) | **Active** |
| **edda_templates** | Embedded application templates | **Active** |
| **edda_screenshot** | Browser automation for UI validation | **Active** |
| **edda_mq** | Event sourcing, aggregate management, persistence (SQLite/PostgreSQL) | Stable (infra for edda_agent) |
| **edda_agent** | Agent orchestration, event handling, coordination, toolbox | Early stage, postponed |
| **edda_cli** | CLI for agent execution | Early stage, postponed |

### Common Commands

```bash
cd edda

# Check all crates compile
cargo check

# Run examples (also serve as integration tests)
cargo run --example basic
cargo run --example planner_worker
cargo run --example multi_agent

# Build MCP server
cargo build --release --package edda_mcp

# Run MCP server (for development)
cargo run --manifest-path edda_mcp/Cargo.toml

# Run tests
cargo test

# Install MCP server locally
curl -LsSf https://raw.githubusercontent.com/appdotbuild/agent/refs/heads/main/edda/install.sh | sh
```

### Core Patterns

#### Agent Trait

All agents implement:
```rust
pub trait Agent: Default + Send + Sync + Clone {
    const TYPE: &'static str;
    type AgentCommand: Send;
    type AgentEvent: MQEvent;
    type AgentError: std::error::Error + Send + Sync + 'static;
    type Services: Send + Sync;

    async fn handle_tool_results(
        state: &AgentState<Self>,
        services: &Self::Services,
        incoming: Vec<ToolResult>,
    ) -> Result<Vec<Event<Self::AgentEvent>>, Self::AgentError>;

    async fn handle_command(
        state: &AgentState<Self>,
        cmd: Self::AgentCommand,
        services: &Self::Services,
    ) -> Result<Vec<Event<Self::AgentEvent>>, Self::AgentError>;

    fn apply_event(state: &mut AgentState<Self>, event: Event<Self::AgentEvent>);
}
```

#### Event Sourcing Pattern

Commands → Events → State:
1. Command received (e.g., `SendRequest`)
2. Handler validates and emits events
3. Events persisted to event store
4. State updated via `apply_event`
5. Listeners dispatch events to handlers

#### Multi-Agent Coordination

Use `Link` trait for agent-to-agent communication:
```rust
link_runtimes(&mut main_runtime, &mut specialist_runtime, CustomLink);
```

Example: Main agent delegates Databricks exploration to specialist agent with haiku model for cost optimization.

#### Tool Execution

All tools run in Dagger sandbox with isolated filesystem. Tools implement:
```rust
pub trait Tool: Send + Sync {
    fn name(&self) -> String;
    fn definition(&self) -> ToolDefinition;
    async fn call(&self, args: Value, sandbox: &mut impl Sandbox) -> Result<String>;
}
```

### Key Files

- **edda/docs/DESIGN.md** - Complete system design with diagrams
- **edda/CLAUDE.md** - Edda-specific development guidance
- **edda_agent/src/processor/agent.rs** - Agent trait and runtime
- **edda_agent/src/processor/link.rs** - Multi-agent coordination
- **edda_agent/src/toolbox/basic.rs** - Core tools (ReadFile, WriteFile, Bash, etc.)
- **edda_mq/src/aggregate.rs** - Event sourcing primitives
- **edda_mcp/src/main.rs** - MCP server implementation

### Environment Variables

```bash
# LLM providers
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...

# Databricks (if using)
DATABRICKS_HOST=https://your-workspace.databricks.com
DATABRICKS_TOKEN=dapi...

# Logging
RUST_LOG=edda=debug,edda_agent=trace
```

### Adding New Components

**New Agent:**
1. Implement `Agent` trait with custom command/event types
2. Define `handle_tool_results` and `handle_command` methods
3. Implement `apply_event` for state reconstruction
4. Create `Runtime` with handlers (LLM, Tool, Log)

**New Tool:**
1. Implement `Tool` trait in `edda_agent/src/toolbox/`
2. Define tool name and schema via `definition()`
3. Implement `call()` method with sandbox execution
4. Register in tool handler

**New Integration:**
1. Add client in `edda_integrations/`
2. Create tools wrapping integration API
3. Add MCP tools in `edda_mcp/src/tools/` if needed

## Klaudbiusz - Databricks App Generator (Python)

AI-powered Databricks application generator achieving **90% success rate** (18/20 apps deployable).

### Structure

- **cli/** - Generation (`main.py`, `codegen.py`) and evaluation (`evaluate_all.py`) scripts
- **agents/** - Claude Agent definitions (markdown format with YAML frontmatter)
- **app/** - Generated TypeScript full-stack applications (gitignored)
- **eval-docs/** - 9-metric evaluation framework documentation

### Common Commands

```bash
cd klaudbiusz

# Generate single app
uv run cli/main.py "Create customer churn analysis dashboard"

# Batch generate from prompts
uv run cli/bulk_run.py

# Evaluate all apps
python3 cli/evaluate_all.py

# Archive evaluation results
./cli/archive_evaluation.sh
```

### Integration with Edda

Klaudbiusz uses edda's MCP server via Claude Agent SDK:
- `AppBuilder` class spawns `edda_mcp` binary
- Agents use tools: `scaffold_data_app`, `validate_data_app`, `databricks_*`
- Subagent pattern: main agent delegates to `dataresearch` agent for Databricks exploration

## General Development Guidelines

### Rust (edda)

- Always run `cargo check` after changes
- Leverage Rust type system: match by type, not string conditions
- Rust chosen for correctness: avoid implicit fallbacks
- Use async/await with Tokio runtime
- Event sourcing: Commands → Events → State (never modify state directly)
- Handlers should be idempotent
- Use `tracing` crate for instrumentation
- Examples double as integration tests

### Python (klaudbiusz)

- Use `uv` for package management: `uv run python ...`
- Type safety is mandatory: run `uv run pyright .` after changes
- Run `uv run ruff check . --fix` for linting
- No silent failures: explicit error handling
- Prefer modern patterns (match over if)
- Never use lazy imports

### Git Workflow

- Short commit messages (no Claude Code mentions)
- Use `gh` CLI for GitHub operations
- Check `.edda_state` in klaudbiusz apps before committing

### Release Workflow (edda_mcp)

Automatic releases triggered when **both** conditions met:
1. `edda/edda_mcp/Cargo.toml` version changed
2. Last commit has `[release]` keyword (or push to main)

**Version rules:**
- PR releases: MUST use dev format (`0.0.3-dev.1`) → creates prerelease
- Main releases: MUST use stable format (`0.0.4`) → creates latest release
- Tag must not exist → fails if duplicate

**Example workflow:**
1. Change version to `0.0.5-dev.1` in Cargo.toml
2. Commit with `[release] Add new feature`
3. CI builds, tests, creates GitHub release v0.0.5-dev.1
4. After merge to main, bump to `0.0.5` and commit (no `[release]` needed on main)

### Testing

**Edda:**
- In-memory SQLite for fast tests
- Run examples as integration tests
- Test event replay and state reconstruction

**Klaudbiusz:**
- 9 objective metrics (build, runtime, type safety, tests, DB connectivity, data returned, UI renders, runability, deployability)
- See `eval-docs/evals.md` for metric definitions

## Documentation

- **edda/docs/DESIGN.md** - Complete Edda architecture with diagrams
- **edda/CLAUDE.md** - Edda-specific development guidance
- **klaudbiusz/README.md** - Klaudbiusz overview and usage
- **klaudbiusz/eval-docs/** - Evaluation framework documentation
- remember how release logic works