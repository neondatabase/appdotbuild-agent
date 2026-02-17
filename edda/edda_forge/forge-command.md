Delegate coding tasks to edda-forge — a sandboxed agent that loops (plan → implement → validate → review) until the code compiles and tests pass, then produces a validated patch. Think of it as delegating to an engineer who returns a tested diff.

Use forge when subtasks are self-contained. Forge runs in an isolated Dagger container, so the user's working tree stays clean until a validated patch is applied.

Your primary responsibility is orchestration quality: decompose well, maximize safe parallelism, keep ownership boundaries clear, and avoid patch conflicts.

The problem is: $ARGUMENTS

## 0. Decompose first (strict protocol)

Before running anything, create a task DAG and validate it.

### Output format (required)

Produce a plan in this exact shape:

```markdown
## Task DAG
- T1: <name>
  - goal: <specific deliverable>
  - depends_on: [T? ...]
  - owned_paths: [glob, glob, ...]
  - validate: <single targeted command>
  - prompt_summary: <1-2 lines>
```

Use these rules:
- Decompose proportionally. Use `3-5` tasks when that is enough. Use more only when it clearly increases parallelism or isolation.
- Every task must have clear file ownership (`owned_paths`). Avoid overlap across parallel tasks.
- Prefer vertical slices (`feature + tests`) over horizontal slices (`models first, then services, then tests`).
- Put shared glue/init files (e.g. `mod.rs`, `lib.rs`, `index.ts`, `__init__.py`) into later integration tasks, not early parallel tasks.
- If two tasks must touch the same file, add a dependency edge (`depends_on`) or restructure tasks.
- Each task must have one focused validation command (targeted test/module where possible).
- No vague tasks ("improve", "cleanup", "polish"). Every task must produce concrete code and tests.

### Special playbook: rewrite project to Rust while keeping source tests

When the goal is "rewrite project to Rust while keeping original test suite":
- Keep existing tests as the source of truth.
- Ignore original implementation files unless needed only for behavior reference.
- Start with one core/bootstrap task (`T1`) to create crate structure, test harness wiring, and minimal API surface needed for tests to run.
- Then create `N` feature tasks, preferably one per test file (or per coherent test group).
- Feature tasks should depend on `T1` and be parallelizable with each other when they own separate modules.
- Add a final integration task to unify exports, resolve shared types, and run full test suite.

Only continue when the DAG is coherent (acyclic, ownership conflicts resolved, validation commands present).

## 1. Check forge.toml

Look for `forge.toml` in the project root.
If it doesn't exist, detect the project type and create one.

### Concurrent runs with different validation targets

When running multiple forge instances against different test files or modules, create separate config files (e.g. `forge-auth.toml`, `forge-api.toml`) each with a targeted test command. Pass them via `--config`:

```bash
edda-forge --config forge-auth.toml --prompt '...' --source . --output ./forge-auth
edda-forge --config forge-api.toml --prompt '...' --source . --output ./forge-api
```

The configs should differ only in the validation step. Keep one shared base `forge.toml` for solo runs.

### Templates

**Rust** (Cargo.toml present):
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
PATH = "/home/forge/.local/bin:/home/forge/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CARGO_HOME = "/home/forge/.cargo"
RUSTUP_HOME = "/home/forge/.rustup"

[project]
language = "rust"
source = "."
workdir = "/app"

[steps]
[[steps.validate]]
name = "check"
command = "cargo check 2>&1"
[[steps.validate]]
name = "test"
command = "cargo test 2>&1"
```

**TypeScript/JavaScript** (package.json present):
```toml
[container]
image = "node:20"
setup = ["apt-get update && apt-get install -y git sudo"]
user = "forge"
user_setup = """
useradd -m -s /bin/bash forge \
  && echo 'forge ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
"""

[container.env]
PATH = "/home/forge/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[project]
language = "typescript"
source = "."
workdir = "/app"

[steps]
[[steps.validate]]
name = "install"
command = "npm install 2>&1"
[[steps.validate]]
name = "build"
command = "npm run build 2>&1"
[[steps.validate]]
name = "test"
command = "npm test 2>&1"
```

**Python** (pyproject.toml present):
```toml
[container]
image = "python:3.12"
setup = ["apt-get update && apt-get install -y curl git sudo"]
user = "forge"
user_setup = """
useradd -m -s /bin/bash forge \
  && echo 'forge ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers \
  && curl -LsSf https://astral.sh/uv/install.sh | su - forge -c bash
"""

[container.env]
PATH = "/home/forge/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[project]
language = "python"
source = "."
workdir = "/app"

[steps]
[[steps.validate]]
name = "install"
command = "uv sync 2>&1"
[[steps.validate]]
name = "lint"
command = "uv run ruff check . 2>&1"
[[steps.validate]]
name = "typecheck"
command = "uv run pyright . 2>&1"
[[steps.validate]]
name = "test"
command = "uv run pytest 2>&1"
```

**Python + Rust / maturin** (both pyproject.toml and Cargo.toml, with `[tool.maturin]` or `maturin` in build-system):
```toml
[container]
image = "python:3.12"
setup = [
    "apt-get update && apt-get install -y curl git sudo build-essential",
]
user = "forge"
user_setup = """
useradd -m -s /bin/bash forge \
  && echo 'forge ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers \
  && su - forge -c 'curl --proto =https --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y' \
  && su - forge -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
"""

[container.env]
PATH = "/home/forge/.local/bin:/home/forge/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CARGO_HOME = "/home/forge/.cargo"
RUSTUP_HOME = "/home/forge/.rustup"

[project]
language = "python"
source = "."
workdir = "/app"

[steps]
[[steps.validate]]
name = "sync"
command = "uv sync 2>&1"
[[steps.validate]]
name = "build-rust"
command = "uv run maturin develop 2>&1"
[[steps.validate]]
name = "test"
command = "uv run pytest 2>&1"
```

Note: Rust and uv are installed as the forge user (via `su - forge -c`), not as root. This avoids permission errors when `maturin` or `cargo` run later.

Show the generated forge.toml to the user and ask for confirmation before writing it.

## 2. Generate per-task prompts and config variants

For each DAG task:
- Expand `prompt_summary` into a precise prompt with explicit acceptance criteria.
- Mention exact files/modules and exact tests that must pass.
- In Rust rewrite scenarios, include expected signatures/invariants from the related tests.
- Generate a unique output path and dedicated config file (`forge-<task>.toml`) with targeted validation.

Always specify a unique output path:

```bash
edda-forge --config forge-<task>.toml --prompt '<task prompt>' --source . --output ./forge-<task> --max-retries 3
```

ANTHROPIC_API_KEY must be set.

## 3. Execute by DAG waves (parallel where safe)

Run tasks by dependency waves:
- Wave = tasks whose `depends_on` are complete.
- Launch tasks in the same wave concurrently.
- Keep a practical concurrency cap based on environment stability.

If running multiple forge instances concurrently, launch each in the background and wait for all to complete. Forge tasks take time, so do not poll too frequently — give at least 5 minutes before first progress check.

### Prompt quality matters

For simple tasks ("add a logging middleware"), a short prompt is fine. For algorithmic or precision-sensitive tasks, include the exact contract in the prompt — do not just say "study the test file." Spell out:
- The exact function signatures and return types
- Key invariants and assertions the code must satisfy
- Edge cases (zero weights, NaN handling, empty inputs)

A vague prompt that fails review 3 times wastes more time than a detailed prompt that succeeds on the first try.

### Choosing `--max-retries`

- Simple tasks (wrapping existing APIs, straightforward CRUD): `--max-retries 3`
- Complex tasks (algorithms, precision-sensitive, many edge cases): `--max-retries 5`

## 4. Apply and clean up

On success (exit 0), apply each patch sequentially:
```bash
git apply forge-<slug>.patch && rm forge-<slug>.patch
```

### Handling patch conflicts across concurrent runs

When multiple forge instances modify overlapping files (e.g. `__init__.py`, `conftest.py`), later patches will fail to apply. 

Solutions, in order of preference:

1. **Exclude conflicting files, merge manually.** Apply the patch excluding known conflicts, then hand-merge the conflicting files:
   ```bash
   git apply --exclude='path/to/conflict.py' forge-<slug>.patch
   ```
   Then read the excluded hunks from the patch and apply the relevant parts via Edit.

2. **Commit between patches and use 3-way merge.** After applying each patch, commit it. Then apply the next with `--3way`:
   ```bash
   git apply forge-first.patch && git add -A && git commit -m "apply first"
   git apply --3way forge-second.patch
   ```

3. **Apply dependency order.** Use DAG order first; within same wave, apply most independent patches first.

On forge failure: show the error and suggest the user refine the prompt or adjust forge.toml validation steps.

## 5. Verify

Run the **actual target tests** locally after applying patches — not just a build check. The container environment may differ from local (different random seeds, dependency versions, etc.):

```bash
# Python
uv run pytest tests/ -x -q

# Rust
cargo test

# TypeScript
npm test
```

Show `git diff --stat` so the user can review what changed.

Clean up any leftover forge config and patch files:
```bash
rm -f forge-*.toml forge-*.patch
```
