# forge — implementation spec

## What this tool does

Forge is a Rust CLI that takes a TOML config file describing a coding task and produces a validated git patch. It does this by driving [Claude Code CLI](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) through a deterministic state machine with automatic retries.

The key idea: forge creates an **isolated temporary workspace**, copies source files into it, then runs Claude Code multiple times in a structured loop — first to plan, then to implement, then to validate (build/test), then to review. If validation or review fails, it automatically creates fix tasks and loops back. The output is a `.patch` file that has passed all configured checks.

**Design for scale:** a single TOML file fully describes a forge run — the prompt, the source, the validation, the output. This means an orchestrator can template hundreds of TOML configs and spawn forge processes in parallel, each producing an independent validated patch. Forge itself is always a single run; parallelism is the caller's problem.

This is a **greenfield implementation**. There is no existing code to modify — build everything from scratch.

---

## High-level flow

```
User runs:  forge --config task-auth.toml

  1. Load config (prompt, source, validation steps, etc.)
  2. Create isolated temp workspace, copy source files in
  3. Init git repo in workspace (baseline commit)
  4. State machine loop:
     Plan  →  Work  →  Validate  →  Review  →  Export
  5. Output: validated .patch file
```

---

## State machine

The core of forge is a state machine with these states:

```
Init { prompt }
  │
  ▼
Plan { prompt }
  │  Agent creates tasks.md (checkbox task list) from the prompt
  │  Fail: empty plan or exec error → Failed
  ▼
Work
  │  Agent works on unchecked tasks, marks them done
  │  If all tasks done → Validate
  │  If progress made but tasks remain → Work (loop)
  │  If no progress (no new checkmarks) → Failed
  ▼
Validate { step_idx }
  │  Run validation commands in order (e.g. cargo check, cargo test)
  │  If step passes → next step
  │  If all steps pass → Review
  │  If step fails → append fix task to tasks.md, go back to Work
  │  If retries exhausted → Failed
  ▼
Review
  │  Agent reviews the git diff against rubrics
  │  APPROVED → Export
  │  REJECTED → append fix task, go back to Work
  │  Invalid response → retry Review
  │  If retries exhausted → Failed
  ▼
Export → Done
  │  Generate .patch file
  ▼
Done | Failed { reason }
```

**Key invariants:**
- Separate retry counters for validate and review (both capped by `max_retries` from config)
- `tasks.md` is append-only — failures add `- [ ] Fix: ...` entries, never revert previous work
- Every state transition is raced against Ctrl+C (`tokio::select!` with `ctrl_c` signal)
- Work fails immediately if an iteration produces zero newly checked tasks (prevents infinite loops)

---

## Agent interaction

Forge drives Claude Code CLI (`claude`) as a subprocess. It never calls the Anthropic API directly.

### How to invoke Claude Code

```bash
claude -p '<prompt>' --dangerously-skip-permissions [--model <model>] [--output-format stream-json --verbose]
```

- `-p` runs Claude in non-interactive "print" mode with the given prompt
- `--dangerously-skip-permissions` lets Claude execute tools without asking
- `--model` is optional, set from config
- `--output-format stream-json --verbose` enables trajectory logging (used for plan/work, NOT for review)

Run via `sh -c "..."` with:
- `current_dir` set to workspace workdir
- `process_group(0)` — own process group so kill takes the whole child tree
- `kill_on_drop(true)` — cleanup on parent exit

Single-quote the prompt. Escape any `'` in the prompt as `'\''`.

### What forge tells the agent

**Plan step prompt:**
```
You are working in {workdir}, a {language} project.
The user wants: {prompt}

Create a file called {workdir}/tasks.md with a markdown checkbox task list
that breaks this down into implementation steps. Use this format:
- [ ] First task
- [ ] Second task

Include writing tests as part of the plan.
Focus on the public API, data structures, and key algorithms.
Do NOT write any code yet — only the task list.
```

**Work step prompt:**
```
You are working in {workdir}, a {language} project.
Here is the current task list from {workdir}/tasks.md:

{contents of tasks.md}

Work on the unchecked tasks (- [ ]). For each task you complete,
update {workdir}/tasks.md to mark it as done (- [x]).
You may complete multiple tasks in one go.
Focus on correctness.

IMPORTANT: Do NOT create summary/report files (SUMMARY.md, REPORT.md, etc.),
scratch test scripts at the project root, or virtual environments.
Only create files that are part of the project deliverable.
```

**Review step prompt:**
```
You are a {language} code reviewer working in {workdir}.
Review the staged changes (run `git diff --cached {diff_pathspec}` to see the diff).

Task list:
{contents of tasks.md}

Evaluate the code against these criteria:
1. {rubric_1}
2. {rubric_2}
...

Respond ONLY with one of:
APPROVED
REJECTED: <which criteria failed and why>

No analysis, no markdown, no explanation — just the verdict line.
```

### Task tracking via tasks.md

`tasks.md` is a markdown file with checkbox items that serves as the shared contract between plan/work/validate/review steps:

```markdown
- [ ] Implement the Foo struct with new() and get() methods
- [ ] Add unit tests for Foo
- [x] Set up module structure
```

Parsing rules:
- `- [x]` or `- [X]` = done
- `- [ ]` = pending
- Everything else is ignored

When validation or review fails, forge appends a new unchecked task:
```
- [ ] Fix: `cargo test` failed (attempt 2) — error: expected struct `Foo`, found `Bar`
```

This gives the agent full context of what was tried and what failed.

---

## Workspace isolation

Every forge run operates in a fresh temporary directory. The user's source tree is never modified.

### Setup sequence

1. Create a `tempfile::tempdir()` — auto-cleaned on drop.
2. Normalize `project.workdir` from config: strip leading `/`, reject `..` components. Example: `/app` → `app`.
3. Create `{tempdir}/{normalized_workdir}/`.
4. Copy `project.source` directory into the workdir, skipping files matching `project.exclude` glob patterns.
5. For each `[[mounts]]` entry: resolve `host` path (expand `~` to `$HOME`, resolve relative paths against config file directory), then copy into `{workdir}/{target}`.
6. Build env map: forward `ANTHROPIC_API_KEY` from host if set.

### Workspace struct

```rust
struct Workspace {
    root: PathBuf,                    // tempdir root
    workdir: PathBuf,                 // root.join(normalized_workdir)
    env: HashMap<String, String>,     // env vars for child processes
    _tempdir: tempfile::TempDir,      // dropped = dir deleted
}
```

Methods:
- `exec(&mut self, command: &str) -> Result<ExecResult>` — run shell command in workdir
- `read_file(&self, path: &str) -> Result<String>` — read file (absolute or relative to workdir)
- `write_file(&mut self, path: &str, content: &str) -> Result<()>` — write file

```rust
struct ExecResult {
    exit_code: i32,
    stdout: String,
    stderr: String,
}
```

### Path resolution

When a file path is given:
- Absolute paths: join with `root` (so `/app/foo.rs` → `{tempdir}/app/foo.rs`)
- Relative paths: join with `workdir`
- Reject any path containing `..` components

### Source copying with include/exclude globs

Use the `globset` crate. Build two `GlobSet`s:
- **include** from `project.include` patterns (if non-empty)
- **exclude** from `project.exclude` patterns

Walk the source directory recursively. For each entry, compute its path relative to the source root:
1. If `include` is non-empty: skip the file unless it matches at least one include pattern **or** is an ancestor directory of an included path.
2. Skip if the path matches any exclude pattern.
3. Only copy regular files and directories (skip symlinks).

When `project.include` is empty (or omitted), all files pass the include filter — this preserves backward compatibility.

**Important for include semantics:** when a glob like `services/auth/**` is specified, ancestor directories (`services/`, `services/auth/`) must be created even though they don't literally match the glob. The implementation should either:
- Always create parent directories for any matched file, or
- Treat directory entries as "included" if they are a prefix of any include pattern.

---

## Configuration

Every forge run is fully described by a single TOML file. The prompt, source location, validation steps, output preferences, and review rubrics are all in one place. This makes it easy for an orchestrator to template configs for batch runs.

### forge.toml format

```toml
# The task prompt — what the agent should build or change.
# This is the only field without a default; it must be provided
# either here or via --prompt CLI override.
prompt = "Implement an LRU cache with get, put, and configurable max size"

# Agent configuration. Optional, defaults to "claude" (no model override).
# Format: "claude" or "claude:<model-id>"
agent = "claude:claude-sonnet-4-5-20250929"

[project]
language = "rust"          # used in prompts to the agent (e.g. "a rust project")
source = "."               # root directory to copy from (relative to config file)
workdir = "/app"           # logical workdir path (leading / is stripped for tempdir layout)
include = [                # glob patterns for files to copy (empty = copy everything)
    "services/auth/**",    # only copy these subtrees from source
    "shared/types/**",
    "Cargo.toml",
    "Cargo.lock",
]
exclude = [                # glob patterns excluded from source copy (applied after include)
    ".git", "**/.git", "**/.git/**",
    "target", "**/target", "**/target/**",
    "node_modules", "**/node_modules", "**/node_modules/**",
    ".venv", "**/.venv", "**/.venv/**",
    "__pycache__", "**/__pycache__", "**/__pycache__/**",
]

# Optional: extra host paths to copy into workspace
[[mounts]]
host = "~/.claude"         # host path (~ expanded, or relative to config dir)
target = ".claude"         # destination relative to project.workdir

# Output path for .patch file (default: ./forge-output → writes ./forge-output.patch)
output = "./forge-output"

[patch]
exclude = [                # glob patterns excluded from output diff
    "tasks.md",
    "*SUMMARY*.md",
    "*REPORT*.md",
    "*venv*/**",
    "__pycache__/**",
    "target/**",
    "node_modules/**",
]

[review]
# Optional rubrics for the review step. If omitted, hardcoded defaults are used.
# When provided, these REPLACE the defaults entirely.
rubrics = [
    "no obvious bugs or logic errors",
    "no security vulnerabilities (injection, path traversal, hardcoded secrets)",
    "no dead code or unused imports",
    "error handling: no swallowed errors, no unwrap on fallible paths",
    "tests cover the stated requirements",
]

# Max retries for validate/review failures (default: 3)
max_retries = 3

# Ordered validation steps. At least one is required.
[steps]
[[steps.validate]]
name = "check"
command = "cargo check 2>&1"

[[steps.validate]]
name = "test"
command = "cargo test 2>&1"
```

### Config resolution

The CLI accepts `--config <path>` pointing to a TOML file. This is the primary interface.

Resolution order when `--config` is not provided:
1. `forge.toml` in current working directory
2. Built-in default (Rust project with `cargo check` + `cargo test`, no prompt)

If no config provides a prompt and `--prompt` is not passed either, exit with an error.

### CLI overrides

A few config fields can be overridden from the CLI for convenience. CLI values take precedence over config values:

- `--prompt <TEXT>` overrides `prompt`
- `--source <DIR>` overrides `project.source`
- `--output <PATH>` overrides `output`
- `--max-retries <N>` overrides `max_retries`

This lets you use a shared base config and vary per-run parameters:
```bash
# same config, different prompts
forge --config base.toml --prompt "add auth middleware"
forge --config base.toml --prompt "add rate limiting"
```

### Batch / template use case

An orchestrator can generate many TOML files from a template and run them in parallel:

```python
# orchestrator pseudocode
template = open("forge-template.toml").read()
for feature in features:
    config = template.replace("{{prompt}}", feature.prompt)
    config = config.replace("{{output}}", f"./patches/{feature.slug}")
    write(f"forge-{feature.slug}.toml", config)
    spawn(f"forge --config forge-{feature.slug}.toml")
```

Each forge process runs in its own tempdir, so there's no interference between parallel runs. The orchestrator collects patches and applies them.

### Built-in default config

When no config file is found, use this hardcoded default:

```rust
// prompt: None (must come from --prompt or error)
// agent: claude, no model override
// project.language: "rust"
// project.source: "."
// project.workdir: "/app"
// project.include: [] (empty = copy everything)
// project.exclude: [".git", "**/.git", "**/.git/**", "target", "**/target", "**/target/**", ...]
// output: "./forge-output"
// steps.validate: [cargo check 2>&1, cargo test 2>&1]
// patch.exclude: [tasks.md, *SUMMARY*.md, *REPORT*.md, ...]
// review.rubrics: None (use defaults)
// max_retries: 3
// mounts: []
```

### Config validation rules

- `prompt` must be non-empty (after merging config + CLI)
- `project.language` must not be empty
- `project.workdir` must not be empty
- `project.include` entries (if present) must be valid glob patterns
- `steps.validate` must have at least one entry
- Mount `host` must not be empty
- Mount `target` must be relative (no leading `/`), no `..` components, not empty
- `agent` string must be `"claude"` or `"claude:<model>"` — anything else is a parse error

### Agent config parsing

The `agent` field is a string with format `"claude"` or `"claude:<model>"`:

```
"claude"                            → model = None
"claude:claude-sonnet-4-5-20250929" → model = Some("claude-sonnet-4-5-20250929")
"anything-else"                     → error
```

Implement a custom serde `Deserialize` for this.

### Default review rubrics

When `[review].rubrics` is not set in config, use these defaults:

```
- no obvious bugs or logic errors
- no security vulnerabilities (injection, path traversal, hardcoded secrets)
- no dead code or unused imports
- error handling: no swallowed errors, no unwrap on fallible paths in production code
- tests cover the stated requirements
```

When `[review].rubrics` IS set, use those instead (full replacement, not merge).

---

## Trajectory logging

When Claude Code runs with `--output-format stream-json --verbose`, its stdout is a stream of newline-delimited JSON objects. Parse each line and log structured events via the `tracing` crate.

### JSON line types

**Assistant message** (`type: "assistant"`):
```json
{"type": "assistant", "message": {"content": [
  {"type": "text", "text": "I'll implement the struct..."},
  {"type": "tool_use", "name": "Write", "input": {"path": "src/lib.rs", "content": "..."}}
]}}
```
→ Log each text block at `info` level (truncated to 200 chars), each tool_use at `info` (tool name + truncated args).

**Tool result** (`type: "tool"`):
```json
{"type": "tool", "content": "file written successfully"}
```
→ Log at `debug` level (truncated to 300 chars).

**Result** (`type: "result"`):
```json
{"type": "result", "num_turns": 5, "total_cost_usd": 0.12, "is_error": false}
```
→ Log at `info` level: turns, cost, is_error.

**Unparseable lines**: warn and skip (don't crash).

Use trajectory logging for Plan and Work steps. Do NOT use it for Review (review runs without `--output-format stream-json` for simpler APPROVED/REJECTED parsing).

---

## Output generation

After the state machine reaches Export:

1. Stage everything: `git add -A`
2. Detect binary files: `git diff --cached --numstat` — lines starting with `-\t-\t` are binary
3. Build pathspec: start with `-- .`, add `':(exclude)pattern'` for each `patch.exclude` glob AND each binary file
4. Generate diff: `git diff --cached {pathspec}`
5. Write stdout to `{output}.patch` (add `.patch` extension if output path has no extension)

### Git baseline

Before the state machine starts, set up git in the workspace:

```bash
git init && \
(git symbolic-ref HEAD refs/heads/main >/dev/null 2>&1 || true) && \
git config user.email forge@local && \
git config user.name forge && \
git add -A && git commit -m baseline --allow-empty
```

Also clean up stale `tasks.md` from previous copies: `rm -f tasks.md`.

The git config is repository-local (not `--global`), so concurrent forge runs don't interfere.

---

## CLI

```
forge [OPTIONS]

Options:
  --config <PATH>       Path to forge.toml config file (primary interface)
  --prompt <TEXT>        Override prompt from config (or provide if config has none)
  --source <DIR>        Override project.source from config
  --output <PATH>       Override output from config
  --max-retries <N>     Override max_retries from config
```

All fields have defaults or come from the config file — so `forge --config task.toml` with a complete TOML is the typical invocation. For quick one-offs, `forge --prompt "..."` works with the built-in default config.

### Binary name

`forge` (configured via `[[bin]]` in Cargo.toml).

### Exit codes

- `0` — success (Done state)
- `1` — failure (Failed state)
- `130` — interrupted (Ctrl+C)

### Logging

Use `tracing-subscriber` with `EnvFilter`:
- Default: `forge=info`
- Override via `RUST_LOG` env var

---

## File layout

```
src/
  main.rs       — CLI definition (clap), config resolution, CLI-over-config merging,
                  run(), run_pipeline(), step(), signal handling
  config.rs     — ForgeConfig, AgentConfig, ProjectConfig, MountConfig, ReviewConfig,
                  PatchConfig, StepsConfig, ValidateStep,
                  config loading/validation, path normalization helpers, default configs
  workspace.rs  — Workspace struct, setup_workspace(), exec, read_file, write_file,
                  source copying with include/exclude globs, mount processing
  runner.rs     — agent_cmd(), plan(), work(), review(), append_task(), read_tasks(),
                  parse_task_stats(), run_validate_step(), trajectory log parsing
  state.rs      — State enum, is_terminal(), Display impl
```

---

## Dependencies

```toml
[package]
name = "forge"
version = "0.1.0"
edition = "2024"

[[bin]]
name = "forge"
path = "src/main.rs"

[dependencies]
clap = { version = "4", features = ["derive"] }
tokio = { version = "1", features = ["full"] }
eyre = "0.6"
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
toml = "0.8"
globset = "0.4"
tempfile = "3"
```

No other dependencies.

---

## Error handling

- All fallible functions return `eyre::Result<T>`.
- No custom error types. Use `eyre::eyre!()` for ad-hoc errors, `bail!()` for early returns.
- The `Failed` state carries a reason string — this is logged at `error` level and becomes the exit message.
- Never panic. Never `unwrap()` on fallible paths. Use `?` propagation everywhere.

---

## Concurrency and safety

- Each forge run uses its own tempdir — safe to run multiple instances in parallel.
- Git config is repo-local (not `--global`) — no cross-run interference.
- Child processes use `process_group(0)` + `kill_on_drop(true)` for reliable cleanup.
- Ctrl+C is handled via `tokio::select!` on every state machine step — the signal doesn't need to propagate through child processes manually.

---

## Tests

### Unit tests (in-crate)

Write `#[cfg(test)]` modules for:

1. **Config parsing**: TOML string → `ForgeConfig`. Test valid configs, missing fields, invalid agent strings.
2. **Agent config deserialize**: `"claude"` → model=None, `"claude:foo"` → model=Some("foo"), `"invalid"` → error.
3. **Task stats parsing**: given tasks.md content, verify done/pending counts and task descriptions.
4. **Review rubrics**: default rubrics when config has no `[review]`, custom rubrics when configured.
5. **Path normalization**: `/app` → `app`, `../etc` → error, empty → error.
6. **Include/exclude filtering**: verify that include narrows files, exclude removes from included set, empty include copies all.
7. **Patch pathspec**: given exclude patterns, verify the generated `-- . ':(exclude)...'` string.
8. **Mount validation**: relative target OK, absolute target → error, `..` in target → error.
9. **State Display**: verify each state variant's Display output.
10. **CLI-over-config merge**: verify --prompt overrides config prompt, --source overrides config source, etc.

### Integration test

The `examples/pure_forge_todo/` directory contains a two-pass example:
- Pass 1: generate a Streamlit todo app from an empty seed
- Pass 2: generate a "clowny UI" patch against the app from pass 1

This requires Claude Code CLI and `ANTHROPIC_API_KEY` — not for CI, just for manual verification.

---

## Detailed implementation notes

### `main.rs` structure

```rust
#[tokio::main]
async fn main() -> ExitCode {
    // init tracing
    // match run().await → ExitCode::SUCCESS / FAILURE / 130
}

async fn run() -> Result<()> {
    // parse CLI
    // load config: --config path, or forge.toml in cwd, or built-in default
    // apply CLI overrides (--prompt, --source, --output, --max-retries)
    // validate merged config (prompt must be non-empty, etc.)
    // resolve source path
    // setup workspace
    // run_pipeline()
}

async fn run_pipeline(ws: &mut Workspace, config: &ForgeConfig) -> Result<()> {
    // git init + baseline commit
    // rm -f tasks.md
    // state machine loop with tokio::select! ctrl_c
    // on Done: generate patch
    // on Failed: bail with reason
}

async fn step(state: State, ws: &mut Workspace, config: &ForgeConfig, ...) -> State {
    // match state, call runner functions, return next state
}
```

### Config merging

```rust
// After loading ForgeConfig from TOML (or default):
if let Some(prompt) = cli.prompt {
    config.prompt = Some(prompt);
}
if let Some(source) = cli.source {
    config.project.source = source.to_string_lossy().to_string();
}
if let Some(output) = cli.output {
    config.output = output.to_string_lossy().to_string();
}
if let Some(retries) = cli.max_retries {
    config.max_retries = retries;
}
// Then validate: config.prompt must be Some and non-empty
```

### `runner.rs` — function signatures

All runner functions take `&mut Workspace` and relevant config slices. They use `Workspace::exec` to run commands and `Workspace::read_file`/`write_file` for tasks.md.

```rust
// helper: compute tasks.md path from workdir
fn tasks_path(workdir: &str) -> String;

// plan, work, review — drive the agent via Workspace::exec(agent_cmd(...))
async fn plan(ws: &mut Workspace, agent: &AgentConfig, prompt: &str, language: &str, workdir: &str) -> Result<()>;
async fn work(ws: &mut Workspace, agent: &AgentConfig, language: &str, workdir: &str) -> Result<()>;
async fn review(ws: &mut Workspace, agent: &AgentConfig, language: &str, workdir: &str, diff_pathspec: &str, rubrics: &[String]) -> Result<ReviewVerdict>;

// task list helpers
async fn read_tasks(ws: &mut Workspace, workdir: &str) -> Result<String>;
async fn append_task(ws: &mut Workspace, description: &str, workdir: &str) -> Result<()>;
fn parse_task_stats(task_list: &str) -> TaskStats;

// validation
async fn run_validate_step(ws: &mut Workspace, step: &ValidateStep) -> Result<ExecResult>;
```

**Review staging:** the `review()` function must run `git add -A` before invoking the agent, so the agent sees staged changes via `git diff --cached`.

### `runner.rs` — agent command construction

```rust
fn agent_cmd(model: Option<&str>, prompt: &str, trajectory: bool) -> String {
    let escaped = prompt.replace('\'', "'\\''");
    let model_flag = model.map(|m| format!(" --model {m}")).unwrap_or_default();
    let traj_flags = if trajectory {
        " --output-format stream-json --verbose"
    } else {
        ""
    };
    format!("claude -p '{escaped}'{model_flag} --dangerously-skip-permissions{traj_flags}")
}
```

### `workspace.rs` — exec implementation

```rust
async fn exec(&mut self, command: &str) -> Result<ExecResult> {
    let mut cmd = tokio::process::Command::new("sh");
    cmd.arg("-c").arg(command).current_dir(&self.workdir);
    for (k, v) in &self.env {
        cmd.env(k, v);
    }
    cmd.process_group(0);
    cmd.kill_on_drop(true);
    let child = cmd.spawn()?;
    let output = child.wait_with_output().await?;
    Ok(ExecResult {
        exit_code: output.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
    })
}
```

### `workspace.rs` — path resolution

```rust
fn resolve_path(&self, path: &str) -> Result<PathBuf> {
    let input = Path::new(path);
    let normalized = normalize_components(input)?;  // strips /, rejects ..
    if input.is_absolute() {
        Ok(self.root.join(normalized))
    } else {
        Ok(self.workdir.join(normalized))
    }
}

fn normalize_components(path: &Path) -> Result<PathBuf> {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Normal(seg) => out.push(seg),
            Component::RootDir | Component::CurDir => {} // skip
            Component::ParentDir => bail!("path traversal not allowed: {}", path.display()),
            Component::Prefix(_) => bail!("windows paths not supported"),
        }
    }
    Ok(out)
}
```

### Truncation helper

Used in logging to avoid enormous log lines:

```rust
fn truncate_tail(s: &str, max: usize) -> &str {
    if s.len() <= max { return s; }
    let mut start = s.len() - max;
    while !s.is_char_boundary(start) { start += 1; }
    &s[start..]
}
```

---

## Example: pure_forge_todo

```
examples/pure_forge_todo/
  forge-base.toml     — config for pass 1 (generate todo app)
  forge-clown.toml    — config for pass 2 (generate clown patch)
  run.sh              — shell script that runs both passes
  README.md           — description
```

**forge-base.toml:**
```toml
prompt = "Create a simple Streamlit todo app with add, complete, and delete functionality."
agent = "claude"

[project]
language = "python+streamlit"
source = "."
workdir = "/app"
exclude = [".git", "**/.git/**", "__pycache__", "**/__pycache__/**", ".venv", "**/.venv/**"]

[patch]
exclude = ["tasks.md", "*SUMMARY*.md", "*REPORT*.md", "*venv*/**", "__pycache__/**"]

[steps]
[[steps.validate]]
name = "uv-setup"
command = "uv init --bare --no-readme 2>/dev/null; uv add --dev ruff"

[[steps.validate]]
name = "python-syntax"
command = "uv run python -m py_compile app.py"

[[steps.validate]]
name = "ruff-lint"
command = "uv run ruff check ."
```

**forge-clown.toml:**
```toml
prompt = "Make the todo app look clowny with circus colors, rainbow heading, and playful labels while preserving behavior."
agent = "claude"

[project]
language = "python+streamlit"
source = "."
workdir = "/app"
exclude = [".git", "**/.git/**", "__pycache__", "**/__pycache__/**", ".venv", "**/.venv/**"]

[patch]
exclude = ["tasks.md", "*SUMMARY*.md", "*REPORT*.md", "*venv*/**", "__pycache__/**"]

[steps]
[[steps.validate]]
name = "python-syntax"
command = "uv run python -m py_compile app.py"

[[steps.validate]]
name = "ruff-lint"
command = "uv run ruff check ."
```

**run.sh** (simplified):
```bash
#!/bin/bash
set -eu
DIR=$(mktemp -d)
mkdir -p "$DIR/seed"

# pass 1: generate todo app from empty seed
forge --config forge-base.toml --source "$DIR/seed" --output "$DIR/todo-base"

# apply pass 1 patch to get the base app
cd "$DIR/seed" && git init && git add -A && git commit --allow-empty -m init
git apply "$DIR/todo-base.patch"

# pass 2: generate clown patch against the base app
forge --config forge-clown.toml --source "$DIR/seed" --output "$DIR/todo-clown"

# verify pass 2 patch applies cleanly on top
git apply "$DIR/todo-clown.patch"
```
