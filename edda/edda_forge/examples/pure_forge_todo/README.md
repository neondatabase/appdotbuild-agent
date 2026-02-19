# Pure Forge Todo Example

This example demonstrates a **pure `edda-forge` two-pass flow**:

1. Generate a simple Streamlit todo app.
2. Run forge again on that output to produce a clowny UI patch.

It uses `--runtime local` and a real Claude Code agent backend.

## Run

```bash
cd edda/edda_forge/examples/pure_forge_todo
./run.sh
```

The script prints a temp workspace path and writes:

- `todo-base/` (generated app)
- `todo-clown.patch` (second-pass patch)

## Requirements

- `edda-forge` installed
- `claude` CLI installed
- Claude auth available (either local Claude Code auth or `ANTHROPIC_API_KEY`)
- Python 3, `uv`, and `ruff` for validation steps
