# edda-forge

Generates validated git patches from natural language prompts. Runs agent (Claude Code or OpenCode) through a deterministic state machine with task tracking and retry logic. Supports both Dagger (`--runtime dagger`, default) and host-local execution (`--runtime local`).

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

Requires either:
- **Dagger runtime** (`--runtime dagger`, default): [Dagger CLI](https://docs.dagger.io/install/) + running Docker daemon
- **Local runtime** (`--runtime local`): no Dagger required, runs directly on the host

Both runtimes require either [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) or [OpenCode](https://github.com/anomalyco/opencode) CLI.

To install the `/forge` slash command for Claude Code (Claude Code only):

```bash
edda-forge --install-claude
```

**OpenCode Setup:** Before using with OpenCode, run `opencode` and `/connect` to authenticate first.  
- `--runtime dagger`: auth files are mounted from `~/.local/share/opencode/auth.json` and `~/.config/opencode/`
- `--runtime local`: host auth/config is used directly

## Usage

**Claude Code (default):**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
edda-forge --prompt "implement an LRU cache"
```
(`ANTHROPIC_API_KEY` is required for `--runtime dagger` with Claude backend.)

**Without Dagger (host-local):**
```bash
edda-forge --runtime local --prompt "implement an LRU cache"
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
- `--source` — source directory copied into the runtime workspace
- `--runtime` — `dagger` (default) or `local` (host execution)
- `--output` — output path (default: `./forge-output`; produces `.patch` by default)
- `--export-dir` — export full directory instead of patch
- `--max-retries` — max retries for validation/review failures (default: 3)

## Pure forge example (two-pass)

For a reproducible pure-forge flow (generate app, then generate a follow-up patch), run:

```bash
cd edda/edda_forge/examples/pure_forge_todo
./run.sh
```

This example uses `--runtime local` and runs forge twice:
- pass 1 exports a Streamlit todo app directory
- pass 2 produces a clowny UI patch against that generated app
- agent backend is real Claude Code (`agent = "claude"`)

Artifacts are written to a temp directory printed by the script.

## Two-repo generation (single run)

For generating code across two repositories in one run, point `project.source` (or `--source`) to a parent directory that contains both repos, then use `project.workdir` as that parent in the sandbox. Example:

```toml
[project]
language = "rust+typescript"
source = "../workspace"   # contains repo-a/ and repo-b/
workdir = "/workspace"
exclude = [".git", "**/.git", "**/.git/**", "target", "**/target/**", "node_modules", "**/node_modules/**"]
```

Validation can then target both repos (for example: `cd repo-a && cargo test`, `cd ../repo-b && npm test`).

This works especially well with `--runtime local` when Dagger access is restricted.

## Mount behavior in local runtime

`[mounts]` is container-oriented by default (`host` → `container`). In `--runtime local`, mounts are restricted to the local workspace for safety:

- If `container` is under `project.workdir`, it is mapped into the local workspace automatically.
- If `container` is outside `project.workdir`, set `local_target` explicitly.
- `local_target` is relative to `project.workdir` in local runtime.

Example:

```toml
[[mounts]]
host = "~/.claude"
container = "/home/forge/.claude"         # used in dagger runtime
local_target = ".claude"                  # used in local runtime

[[mounts]]
host = "../shared/prompts"
container = "/workspace/prompts"
# no local_target needed if project.workdir = "/workspace"
```

## Concurrency notes

- `--runtime local` uses an isolated temporary workspace per run, so multiple forge processes can run in parallel safely.
- Git baseline setup is repository-local (no global git config writes), which avoids cross-run interference.

## Output

By default, edda-forge produces a **unified diff** (`.patch` file). A git baseline is committed after runtime workspace setup, and the final diff captures all changes.

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
source = "."         # codebase to copy into runtime workspace (relative to config file)
workdir = "/app"
exclude = [".git", "target"]  # excluded from source copy

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
- **OpenCode auth:**
  - `--runtime dagger` mounts `~/.local/share/opencode/auth.json` and `~/.config/opencode/`
  - `--runtime local` uses host OpenCode auth/config directly

**`[container]`** — Docker container setup
- `image` — base Docker image
- `setup` — list of shell commands run as root (install deps)
- `user` — non-root user name (Claude CLI requires non-root)
- `user_setup` — shell command to create the user
- `env` — environment variables
- Note: these settings apply to `--runtime dagger`; `--runtime local` uses host environment directly.

**`[project]`** — project settings
- `language` — used in AI prompts (e.g. "rust", "python", "typescript")
- `source` — directory to copy into runtime workspace (relative to config file)
- `workdir` — logical workspace path used by prompts and sandbox APIs
- `exclude` — glob patterns excluded from source copy (default: `.git`, `target`, `node_modules`, `.venv`, `__pycache__`)

**`[[mounts]]`** — additional host paths exposed to runtime
- `host` — host path (supports `~`)
- `container` — absolute container path (required; used by dagger runtime)
- `local_target` — optional path relative to `project.workdir` for `--runtime local`
- Local runtime safety rule: if `container` is outside `project.workdir`, `local_target` is required.

**`[patch]`** — output patch filtering
- `exclude` — glob patterns excluded from the output diff (default: `tasks.md`, `*SUMMARY*.md`, `*REPORT*.md`, `*venv*/**`, `__pycache__/**`)

**`[steps]`** — pipeline configuration
- `validate` — ordered list of validation commands

**`[[steps.validate]]`** — validation step
- `name` — step identifier (used in logs and retry tracking)
- `command` — shell command to run
