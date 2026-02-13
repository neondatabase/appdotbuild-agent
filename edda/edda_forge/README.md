# edda-forge

Generates validated git patches from natural language prompts. Runs agent (Claude Code or OpenCode) inside a Dagger container through a deterministic state machine with task tracking and retry logic. Config-driven — works with any language/stack via `forge.toml`.

## State machine

```
Init → Plan → Work (loop) → Validate → Review → Export → Done
```

- **Plan** — Agent creates a checkbox task list (`tasks.md`) from the prompt, including tests
- **Work** — each iteration calls the agent (e.g., `claude -p` or `opencode run`) to work on unchecked items and mark them done. Loops until all tasks are checked off. Fails if an iteration makes no progress.
- **Validate** — runs configured validation steps (build, test, bench). On failure, appends a fix task to `tasks.md` and loops back to Work.
- **Review** — Agent reviews the git diff for correctness. On rejection, appends a fix task and loops back to Work.
- **Export** — generates a `.patch` file (or exports the full directory)

The task list is append-only — failures add new `- [ ] Fix: ...` entries rather than reverting previous work. This gives the agent full context of what was tried.

## Install

```bash
cargo install --git https://github.com/neondatabase/appdotbuild-agent.git edda_forge
```

Requires [Dagger CLI](https://docs.dagger.io/install/) and a running Docker daemon. Also requires either [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) or [OpenCode](https://github.com/anomalyco/opencode) CLI installed.

To install the `/forge` slash command for Claude Code (Claude Code only):

```bash
edda-forge --install-claude
```

**OpenCode Setup:** Before using with OpenCode, run `opencode` and `/connect` to authenticate first. The auth files will be mounted from `~/.local/share/opencode/auth.json` and `~/.config/opencode/`.

## Usage

**Claude Code (default):**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
edda-forge --prompt "implement an LRU cache"
```

**OpenCode:**
```bash
edda-forge --prompt "implement an LRU cache" --config forge-opencode.toml
```

Or use a single `forge.toml` with agent configuration:
```toml
agent = "opencode:opencode/kimi-k2.5-free"
```

Options:
- `--prompt` — task description
- `--install-claude` — install `/forge` slash command for Claude Code
- `--config` — path to `forge.toml` (default: auto-discovered)
- `--source` — source directory to mount in container
- `--output` — output path (default: `./forge-output`; produces `.patch` by default)
- `--export-dir` — export full directory instead of patch
- `--max-retries` — max retries for validation/review failures (default: 3)

## Output

By default, edda-forge produces a **unified diff** (`.patch` file). A git baseline is committed after container setup, and the final diff captures all changes.

```bash
# default: patch output
edda-forge --prompt "implement a stack" --output my-stack
# → writes my-stack.patch

# directory export
edda-forge --prompt "implement a stack" --output ./out --export-dir
```

## Configuration

edda-forge is driven by `forge.toml`. When no config file is found, a built-in Rust default is used.

```toml
# Agent backend configuration (optional)
# Format: "backend" or "backend:model"
# Default: "claude" (no model required)
# Examples:
# agent = "claude"                          # Claude Code, default model
# agent = "claude:claude-sonnet-4-5-20250929"  # Claude Code with specific model
# agent = "opencode:opencode/kimi-k2.5-free"   # OpenCode with specific model

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
exclude = [".git", "target"]  # not mounted into container

[patch]
exclude = ["tasks.md", "*SUMMARY*.md", "*REPORT*.md", "*venv*/**", "__pycache__/**"]

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

**`agent`** — Agent backend configuration (optional)
- Format: `"backend"` or `"backend:model"` (colon separator)
- Default: `"claude"` (no model required for Claude)
- Backends:
  - `claude` — Claude Code CLI
  - `opencode` — OpenCode CLI
- Examples:
  - `agent = "claude"` — Claude Code with default model
  - `agent = "claude:claude-sonnet-4-5-20250929"` — Claude Code with specific model
  - `agent = "opencode:opencode/kimi-k2.5-free"` — OpenCode with specific model (model required)
- **OpenCode auth:** The following files are mounted from the host:
  - `~/.local/share/opencode/auth.json` — Authentication token
  - `~/.config/opencode/` — Configuration directory

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
- `exclude` — glob patterns excluded from container mount (default: `.git`, `target`, `node_modules`, `.venv`, `__pycache__`)

**`[patch]`** — output patch filtering
- `exclude` — glob patterns excluded from the output diff (default: `tasks.md`, `*SUMMARY*.md`, `*REPORT*.md`, `*venv*/**`, `__pycache__/**`)

**`[steps]`** — pipeline configuration
- `validate` — ordered list of validation commands

**`[[steps.validate]]`** — validation step
- `name` — step identifier (used in logs and retry tracking)
- `command` — shell command to run
