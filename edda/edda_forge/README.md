# edda-forge

Deterministic coding agent that generates Rust libraries from a prompt using Claude Code inside a Dagger container.

## State machine

```
Init → RewriteTask → CloneTemplate → WriteTests → CargoCheck(Tests)
  → WriteCode → CargoCheck(Code) → RunTests → Review → RunBenchmark → Export → Done
```

Failures backtrack with retry limits (default: 3 per edge):
- `CargoCheck(Tests)` fails → retry `WriteTests`
- `CargoCheck(Code)` fails → retry `WriteCode`
- `RunTests` fails → retry `WriteCode`
- `Review` rejects → retry `WriteCode` with reviewer feedback

## Usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cargo run -p edda_forge -- --prompt "implement an LRU cache" --output ./out
```

Options:
- `--prompt` — task description (required)
- `--template` — path to custom project template (default: built-in)
- `--output` — export directory (default: `./forge-output`)
- `--max-retries` — retry limit per backtrack edge (default: 3)
- `--image` — custom base Docker image (default: `rust:latest`)

## Extending

### Custom template

The `--template` flag points to a Rust project directory that gets mounted into the container at `/app`. Claude generates code on top of it.

```
my-template/
├── Cargo.toml
├── src/
│   └── lib.rs            # can be empty or contain scaffolding
├── tests/
│   └── integration.rs    # your pre-written tests
└── benches/
    └── bench.rs          # your pre-written benchmarks
```

### Custom tests

Put your tests at `tests/integration.rs`. The `WriteTests` step tells Claude to write tests there — if the file already has content, Claude sees it and extends it. To preserve your tests, add a marker:

```rust
// === DO NOT MODIFY TESTS ABOVE THIS LINE ===
```

The crate name in `Cargo.toml` matters — tests import it. Default is `forge_project`.

### Custom benchmarks

Put criterion benchmarks in `benches/bench.rs`. `RunBenchmark` runs `cargo bench` — non-fatal, failures won't block export.

Required in `Cargo.toml`:
```toml
[dev-dependencies]
criterion = { version = "0.5", features = ["html_reports"] }

[[bench]]
name = "bench"
harness = false
```

### Adding more test/bench files

```toml
[[test]]
name = "my_other_test"
path = "tests/my_other_test.rs"

[[bench]]
name = "my_other_bench"
harness = false
```

### Custom Docker image

Use `--image` to provide a pre-built image. The image must have `cargo` and `rustc` available. The container setup will still:
1. Install `curl` and `sudo` via `apt-get`
2. Create a non-root `forge` user (Claude CLI refuses `--dangerously-skip-permissions` as root)
3. Install Claude CLI
4. Mount your template at `/app`

```bash
cargo run -p edda_forge -- \
  --prompt "implement an LRU cache" \
  --image my-registry/rust-with-extras:latest \
  --template ./my-template
```

If your image already has a non-root user, Claude CLI, or extra dependencies, you'll need to modify `container.rs` — the setup steps are currently hardcoded.

### Full example

```bash
cargo run -p edda_forge -- \
  --prompt "implement a thread-safe LRU cache with TTL support" \
  --template ./my-lru-template \
  --image rust:1.84 \
  --output ./lru-output \
  --max-retries 5
```
