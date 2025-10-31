# edda_transpiler

MCP server for Python→Rust transpilation with PyO3 bindings. Provides scaffolding, validation, and comprehensive guidelines for converting Python code to Rust while maintaining behavioral equivalence.

## Overview

This tool is designed for AI agents (like Claude Code or Claude Agent SDK) to transpile Python functions to Rust with PyO3 bindings. The MCP server provides:

1. **Scaffolding** - Maturin project structure with Rust stubs
2. **Guidelines** - Comprehensive PyO3 patterns and examples
3. **Validation** - Sandbox-based testing to verify equivalence

The agent writes the actual Rust code following the provided guidelines, then iteratively validates until tests pass.

## Architecture

```
Agent (Claude Code/SDK)
    ↓ calls scaffold_maturin_project
MCP Server (edda_transpiler)
    ↓ returns structure + guidelines
Agent implements Rust functions
    ↓ calls validate_rust_equivalent
MCP Server validates in sandbox
    ↓ returns pass/fail + diffs
Agent fixes issues and repeats
```

## MCP Tools

### 1. `scaffold_maturin_project`

Initialize a maturin project structure with Rust stubs.

**Input:**
```json
{
  "work_dir": "/absolute/path/to/rust/project",
  "python_source": "def add(a: int, b: int) -> int:\n    return a + b",
  "python_module_name": "math_utils",
  "force_rewrite": false
}
```

**Output:**
- Creates complete maturin project structure
- Generates Rust stubs with TODO comments for each Python function
- Returns comprehensive guidelines for implementing PyO3 bindings
- Creates equivalence test templates

**Files created:**
```
work_dir/
├── Cargo.toml              # Rust project config with PyO3
├── pyproject.toml          # Maturin build config
├── src/
│   └── lib.rs              # Rust stubs with TODOs
└── tests/
    └── test_equivalence.py # Test templates
```

### 2. `validate_python_tests`

Validate Python tests in a sandbox before transpiling.

**Input:**
```json
{
  "python_dir": "/absolute/path/to/python/project"
}
```

**Output:**
- Runs pytest in isolated sandbox
- Returns whether tests exist and pass
- Provides detailed output for debugging

**Use case:** Ensure Python tests are working before starting Rust implementation.

### 3. `validate_rust_equivalent`

Validate Rust implementation matches Python behavior.

**Input:**
```json
{
  "python_dir": "/absolute/path/to/python/project",
  "rust_dir": "/absolute/path/to/rust/project"
}
```

**Output:**
- Builds Rust with `maturin develop`
- Runs equivalence tests
- Compares Python vs Rust outputs
- Returns detailed diffs for failures

**Workflow:** Call repeatedly after each fix until all tests pass.

## Usage Example

### With Claude Code

Add to Claude Code's MCP config:

```json
{
  "mcpServers": {
    "edda-transpiler": {
      "command": "/path/to/edda_transpiler"
    }
  }
}
```

Then in Claude Code:

```
User: Transpile my array_utils.py to Rust

Claude Code:
1. Reads array_utils.py
2. Calls scaffold_maturin_project with source
3. Receives guidelines and stubs
4. Implements Rust functions following guidelines
5. Calls validate_rust_equivalent
6. Fixes any failures based on validation output
7. Repeats steps 5-6 until pass
```

### Manual Testing

```bash
# Build
cargo build --release --package edda_transpiler

# Run (for debugging)
RUST_LOG=info cargo run --package edda_transpiler

# The server expects MCP protocol on stdin/stdout
```

## Template Structure

The maturin template includes:

- **Cargo.toml** - PyO3 0.22 with extension-module feature
- **pyproject.toml** - Maturin 1.x build backend
- **src/lib.rs** - Module with #[pymodule] and function registration
- **GUIDELINES.md** - Comprehensive PyO3 patterns (embedded in binary)

### Guidelines Cover:

- Type mapping (Python ↔ Rust)
- Common patterns (lists, strings, dicts, numpy)
- Error handling with PyResult
- Optional arguments
- Testing patterns for equivalence
- Performance tips
- Common pitfalls

## Validation Architecture

Both Python and Rust validation run in Dagger containers for isolation:

**Python validation:**
- Container: `python:3.11-slim`
- Installs pytest
- Runs tests, captures output

**Rust validation:**
- Container: `rust:1.83-slim` with Python
- Installs maturin and pytest
- Builds Rust → Python wheel
- Runs equivalence tests comparing both implementations

## Dependencies

- **Rust 1.83+** - For compilation
- **Docker** - For sandbox execution (via Dagger)
- **rmcp 0.8** - MCP protocol implementation
- **edda_sandbox** - Containerized execution

## Development

```bash
# Check compilation
cargo check --package edda_transpiler

# Run tests (template validation)
cargo test --package edda_transpiler

# Build release binary
cargo build --release --package edda_transpiler

# Binary location
target/release/edda_transpiler
```

## Design Philosophy

1. **Agent-driven** - MCP provides structure, agent provides intelligence
2. **No embedded LLM** - Server is simple, stateless, fast
3. **Guidelines as code** - Template teaches agent PyO3 patterns
4. **Validation loop** - Agent iterates until equivalence achieved
5. **Reuse proven patterns** - Built on edda_sandbox and edda_templates

## Limitations

- Python parsing uses regex (not full AST) - good enough for common cases
- Assumes well-typed Python code for best results
- Requires Docker for validation
- Equivalence testing requires Python tests exist

## Future Enhancements

- Support for Python classes (currently functions only)
- AST-based parsing for complex Python features
- Performance benchmarking in validation
- Integration with more test frameworks beyond pytest

## License

Part of the Edda project. See root LICENSE file.
