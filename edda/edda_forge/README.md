# edda-forge

Generates validated git patches from natural language prompts. Runs Claude Code inside a Dagger container through a deterministic state machine with task tracking and retry logic. Config-driven — works with any language/stack via `forge.toml`.

## State machine

```
Init → Plan → Work (loop) → Validate → Review → Export → Done
```

- **Plan** — Claude creates a checkbox task list (`tasks.md`) from the prompt, including tests
- **Work** — each iteration calls `claude -p` to work on unchecked items and mark them done. Loops until all tasks are checked off. Fails if an iteration makes no progress.
- **Validate** — runs configured validation steps (build, test, bench). On failure, appends a fix task to `tasks.md` and loops back to Work.
- **Review** — Claude reviews the git diff for correctness. On rejection, appends a fix task and loops back to Work.
- **Export** — generates a `.patch` file (or exports the full directory)

The task list is append-only — failures add new `- [ ] Fix: ...` entries rather than reverting previous work. This gives Claude full context of what was tried.

## Usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cargo run -p edda_forge -- --prompt "implement an LRU cache"
```

Options:
- `--prompt` — task description (required)
- `--config` — path to `forge.toml` (default: auto-discovered)
- `--source` — source directory to mount in container
- `--output` — output path (default: `./forge-output`; produces `.patch` by default)
- `--export-dir` — export full directory instead of patch
- `--max-retries` — max retries for validation/review failures (default: 3)

## Output

By default, edda-forge produces a **unified diff** (`.patch` file). A git baseline is committed after container setup, and the final diff captures all changes.

```bash
# default: patch output
cargo run -p edda_forge -- --prompt "implement a stack" --output my-stack
# → writes my-stack.patch

# directory export
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

[[steps.validate]]
name = "check"
command = "cargo check 2>&1"

[[steps.validate]]
name = "test"
command = "cargo test 2>&1"

[[steps.validate]]
name = "bench"
command = "cargo bench 2>&1"
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
- `validate` — ordered list of validation commands

**`[[steps.validate]]`** — validation step
- `name` — step identifier (used in logs and retry tracking)
- `command` — shell command to run
