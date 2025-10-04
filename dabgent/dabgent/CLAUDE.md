# CLAUDE.md - Dabgent Library

This file provides guidance to Claude Code when working with the `dabgent` Rust library.

## Project Documentation

For comprehensive system design and architecture information, refer to:
- **[DESIGN.md](../docs/DESIGN.md)** - Complete system design document with architecture diagrams, component details, and usage patterns

## Library Overview

The `dabgent` library is a modular event-sourced AI agent orchestration system that provides:
- **Event-Sourced Architecture**: Full event history with aggregate state reconstruction
- **Multi-Agent Coordination**: Link multiple agents with bidirectional communication
- **Pluggable LLM Support**: Provider-agnostic LLM integration (Anthropic, Gemini via Rig)
- **Sandboxed Execution**: Dagger-based containerized tool execution
- **Type-Safe Event Handling**: Strongly-typed events, commands, and responses

## Key Modules

- **dabgent_agent** - Agent orchestration, event handling, coordination
- **dabgent_mq** - Event sourcing, aggregate management, persistence
- **dabgent_sandbox** - Isolated tool execution in containers
- **dabgent_integrations** - External service integrations (Databricks, etc.)

## Common Development Tasks

### Adding a New Agent

1. Implement the `Agent` trait with custom command/event types
2. Define `handle_tool_results` and `handle_command` methods
3. Implement `apply_event` for state reconstruction
4. Create a `Runtime` with appropriate handlers (LLM, Tool, etc.)

See `examples/basic.rs` for a complete example.

### Adding a New Tool

1. Implement the `Tool` trait in `toolbox/`
2. Define tool name and schema via `definition()`
3. Implement `call()` method with sandbox execution
4. Register tool in the tool handler

See `toolbox/basic.rs` for existing tool implementations.

### Creating Agent Links

1. Implement the `Link` trait with forward/backward methods
2. Define conversion logic between agent events and commands
3. Use `link_runtimes()` to connect agent runtimes

See `examples/planner_worker.rs` for linking patterns.

## Code Style Guidelines

- Use async/await with Tokio runtime
- Leverage event sourcing patterns (Commands → Events → State)
- Keep handlers stateless and side-effect focused
- Use strong typing for domain events and commands
- Follow Rust naming conventions and idioms

## Testing

- Use in-memory SQLite for fast integration tests
- Test event replay and state reconstruction
- Examples double as integration tests: `cargo run --example basic`
- Unit tests for tool validation logic

## Important Notes

- Always persist events before applying state changes
- Handlers should be idempotent where possible
- Use the `tracing` crate for instrumentation
- Sandbox operations should be containerized for safety
