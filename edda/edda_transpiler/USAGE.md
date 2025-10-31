# Quick Start Guide

## Installation

The binary is located at: `target/release/edda_transpiler` (6.6MB)

To use with Claude Code, add to your MCP config:

```json
{
  "mcpServers": {
    "edda-transpiler": {
      "command": "/Users/arseni.kravchenko/dev/agent/edda/target/release/edda_transpiler"
    }
  }
}
```

## Workflow

### Step 1: Scaffold Project

Agent calls `scaffold_maturin_project` with:
- `work_dir`: Absolute path for Rust project
- `python_source`: Python code to transpile
- `python_module_name`: Name of Python module (for imports)
- `force_rewrite`: Whether to wipe existing directory

**Returns:**
- Maturin project structure
- Rust stubs with TODOs
- Comprehensive PyO3 guidelines

### Step 2: Implement Rust Functions

Agent reads the guidelines and implements Rust equivalents following PyO3 patterns.

Key patterns from guidelines:
```rust
// Basic function
#[pyfunction]
fn add(a: i64, b: i64) -> PyResult<i64> {
    Ok(a + b)
}

// With default args
#[pyfunction]
#[pyo3(signature = (name, greeting="Hello"))]
fn greet(name: String, greeting: &str) -> PyResult<String> {
    Ok(format!("{}, {}!", greeting, name))
}

// Lists
#[pyfunction]
fn double_items(items: Vec<i64>) -> PyResult<Vec<i64>> {
    Ok(items.iter().map(|x| x * 2).collect())
}
```

### Step 3: Validate (Optional)

Before implementing Rust, verify Python tests work:

```json
{
  "tool": "validate_python_tests",
  "arguments": {
    "python_dir": "/path/to/python/project"
  }
}
```

### Step 4: Validate Equivalence

Agent calls `validate_rust_equivalent` with:
- `python_dir`: Path to original Python project
- `rust_dir`: Path to Rust project

**Returns:**
- Success/failure
- Test outputs from both Python and Rust
- Detailed diffs for failures

### Step 5: Iterate

If validation fails:
1. Read validation output carefully
2. Fix Rust implementation
3. Call `validate_rust_equivalent` again
4. Repeat until pass

## Example Session

```
User: "Transpile my math_utils.py to Rust"

Agent:
1. Reads math_utils.py content
2. Calls scaffold_maturin_project:
   {
     "work_dir": "/tmp/math_rust",
     "python_source": "<file content>",
     "python_module_name": "math_utils"
   }

3. Receives stubs and guidelines

4. Implements Rust functions in /tmp/math_rust/src/lib.rs

5. Calls validate_rust_equivalent:
   {
     "python_dir": "/path/to/original",
     "rust_dir": "/tmp/math_rust"
   }

6. If fails, reads error:
   "FAILED: test_add
    Python output: 5
    Rust output: 6"

7. Fixes implementation, repeats step 5

8. Success! All tests pass
```

## Tips for Agents

1. **Always read guidelines** - They contain all PyO3 patterns
2. **Start simple** - Implement basic functions first
3. **Match types carefully** - Python int → Rust i64, str → String
4. **Handle errors** - Return PyResult, use PyErr for exceptions
5. **Test incrementally** - Validate after implementing each function
6. **Read validation output** - It shows exact differences

## Type Cheat Sheet

| Python | Rust |
|--------|------|
| `int` | `i64` |
| `float` | `f64` |
| `str` | `String` |
| `bool` | `bool` |
| `list[T]` | `Vec<T>` |
| `dict[K,V]` | `HashMap<K,V>` |
| `None` | `Option<T>` |

## Sandbox Architecture

Both validations run in Docker containers:
- **Python**: `python:3.11-slim` with pytest
- **Rust**: `rust:1.83-slim` with Python, maturin, pytest

Ensures:
- No host pollution
- Reproducible builds
- Safe execution

## Debugging

Set `RUST_LOG=debug` to see detailed logs:
```bash
RUST_LOG=debug /path/to/edda_transpiler
```

Logs go to stderr (won't interfere with MCP on stdin/stdout).

## Troubleshooting

**"docker not available"**
- Ensure Docker daemon is running
- Check `docker ps` works

**"validation failed to run"**
- Check absolute paths provided
- Verify directories exist
- Look at validation stderr output

**"tests pass in Python, fail in Rust"**
- Check type conversions carefully
- Verify default argument handling
- Look for integer vs float division issues

**"maturin build failed"**
- Check Rust syntax errors in validation output
- Ensure all functions registered in #[pymodule]
- Verify PyO3 syntax correct

## Next Steps

After successful transpilation:
1. Performance benchmark (Rust should be faster)
2. Deploy Rust version with `maturin build --release`
3. Install wheel: `pip install target/wheels/*.whl`
4. Replace Python imports with Rust version

## Support

For issues or questions:
- Check examples/README.md
- Review template GUIDELINES.md
- Examine validation output carefully
- Enable debug logging
