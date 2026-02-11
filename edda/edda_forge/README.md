# edda-forge

Deterministic coding agent that generates code from a prompt using Claude Code inside a Dagger container. Config-driven — works with any language/stack via `forge.toml`.

## State machine

```
Init → RewriteTask → LoadTaskList → [WriteTests →] Validate(Tests)
  → WriteCode → Validate(Code) → Review → Export → Done
```

Failures backtrack with retry limits (default: 3 per edge):
- `Validate(Tests)` fails → retry target specified by step's `retry_on_fail`
- `Validate(Code)` fails → retry target specified by step's `retry_on_fail`
- `Review` rejects → retry `WriteCode` with reviewer feedback

In `Tests` phase, validation steps with `retry_on_fail = "write_code"` are skipped (code doesn't exist yet).

Stale `tasks.md` from previous runs is cleaned up automatically before the state machine starts. Review stage operates on the git diff, not individual files.

## Usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cargo run -p edda_forge -- --prompt "implement an LRU cache"
```

Options:
- `--prompt` — task description (required)
- `--config` — path to `forge.toml` config (default: `forge.toml`)
- `--output` — output path (default: `./forge-output`; produces `.patch` by default)
- `--export-dir` — export full directory instead of patch
- `--max-retries` — retry limit per backtrack edge (default: 3)

## Output

By default, edda-forge produces a **unified diff** (`.patch` file). A git baseline is committed after container setup, and the final diff captures all changes.

```bash
# default: patch output
cargo run -p edda_forge -- --prompt "implement a stack" --output my-stack
# → writes my-stack.patch

# directory export (previous behavior)
cargo run -p edda_forge -- --prompt "implement a stack" --output ./out --export-dir
```

## Configuration

edda-forge is driven by `forge.toml`. When no config file is found, a built-in Rust default is used.

```toml
[container]
image = "rust:latest"
setup = ["apt-get update && apt-get install -y curl sudo git"]
user = "forge"
user_setup = """
useradd -m -s /bin/bash forge \
  && echo 'forge ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers \
  && cp -r /usr/local/cargo /home/forge/.cargo \
  && cp -r /usr/local/rustup /home/forge/.rustup \
  && chown -R forge:forge /home/forge/.cargo /home/forge/.rustup
"""

[container.env]
PATH = "/home/forge/.local/bin:/home/forge/.cargo/bin:..."
CARGO_HOME = "/home/forge/.cargo"
RUSTUP_HOME = "/home/forge/.rustup"

[project]
language = "rust"
source = "."         # codebase to copy into container (relative to config file)
workdir = "/app"

[steps]
write_tests = true   # include WriteTests phase

[[steps.validate]]
name = "check"
command = "cargo check 2>&1"
retry_on_fail = "write_tests"

[[steps.validate]]
name = "test"
command = "cargo test 2>&1"
retry_on_fail = "write_code"

[[steps.validate]]
name = "bench"
command = "cargo bench 2>&1"
retry_on_fail = "write_code"
```

### Config fields

**`[container]`** — Docker container setup
- `image` — base Docker image
- `setup` — list of shell commands run as root (install deps)
- `user` — non-root user name (Claude CLI requires non-root)
- `user_setup` — shell command to create the user
- `env` — environment variables

**`[project]`** — project settings
- `language` — used in AI prompts (e.g. "rust", "python", "typescript")
- `source` — directory to copy into container (relative to config file)
- `workdir` — working directory inside container

**`[steps]`** — pipeline configuration
- `write_tests` — whether to include the WriteTests phase
- `validate` — ordered list of validation commands

**`[[steps.validate]]`** — validation step
- `name` — step identifier (used in logs and retry tracking)
- `command` — shell command to run
- `retry_on_fail` — which AI step to retry: `"write_tests"` or `"write_code"`
