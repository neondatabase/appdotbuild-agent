Delegate a coding subtask to edda-forge — a sandboxed agent that loops (plan → implement → validate → review) until the code compiles and tests pass, then produces a validated patch. Think of it as delegating to an engineer who returns a tested diff.

Use forge when the subtask is self-contained. Forge runs in an isolated Dagger container, so the user's working tree stays clean until the validated patch is applied.

When multiple independent subtasks are requested, run multiple forge instances concurrently (each with a unique --output path). Apply patches sequentially after all complete.

The subtask is: $ARGUMENTS

## 1. Check forge.toml

Look for `forge.toml` in the project root. If it exists, skip to step 2.

If it doesn't exist, detect the project type and create one.

### Concurrent runs with different validation targets

When running multiple forge instances against different test files or modules, create separate config files (e.g. `forge-auth.toml`, `forge-api.toml`) each with a targeted test command. Pass them via `--config`:

```bash
edda-forge --config forge-auth.toml --prompt '...' --source . --output ./forge-auth
edda-forge --config forge-api.toml --prompt '...' --source . --output ./forge-api
```

The configs should differ only in the test step. Keep a single shared `forge.toml` for solo runs.

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

## 2. Run forge

Always specify a unique output path to avoid conflicts between concurrent runs. Derive it from the subtask (e.g. slugified keyword):

```bash
edda-forge --prompt '<the subtask>' --source . --output ./forge-<slug> --max-retries 3
```

ANTHROPIC_API_KEY must be set.

If running multiple forge instances concurrently, launch each in the background and wait for all to complete.

### Prompt quality matters

For simple tasks ("add a logging middleware"), a short prompt is fine. For algorithmic or precision-sensitive tasks, **include the exact contract in the prompt** — don't just say "study the test file." Spell out:
- The exact function signatures and return types
- Key invariants and assertions the code must satisfy
- Edge cases (zero weights, NaN handling, empty inputs)

A vague prompt that fails review 3 times wastes more time than a detailed prompt that succeeds on the first try.

### Choosing `--max-retries`

- Simple tasks (wrapping existing APIs, straightforward CRUD): `--max-retries 3`
- Complex tasks (algorithms, precision-sensitive, many edge cases): `--max-retries 5`

## 3. Apply and clean up

On success (exit 0), apply each patch sequentially:
```bash
git apply forge-<slug>.patch && rm forge-<slug>.patch
```

### Handling patch conflicts across concurrent runs

When multiple forge instances modify overlapping files (e.g. `__init__.py`, `conftest.py`), later patches will fail to apply. This is the most common issue with concurrent forge runs.

Strategies, in order of preference:

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

3. **Apply smallest/most-independent patches first.** Order by: utility modules → core logic → integration/glue code. The glue patches (which touch shared files like `__init__.py`) should go last.

### Forge produced junk files

Forge sometimes creates summary/documentation files (`SUMMARY.md`, `IMPLEMENTATION.md`) or extra test files at the project root. Exclude these when applying:
```bash
git apply --exclude='*.md' --exclude='test_*.py' forge-<slug>.patch
```
Or selectively include only the relevant directories:
```bash
git apply --include='src/*' --include='tests/*' forge-<slug>.patch
```

On forge failure: show the error and suggest the user refine the prompt or adjust forge.toml validation steps.

## 4. Verify

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
