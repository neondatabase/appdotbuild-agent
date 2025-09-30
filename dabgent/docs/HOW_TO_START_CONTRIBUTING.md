# Getting Started with Dabgent Contributions

This guide helps you stand up a local Dabgent development environment and understand where to begin making changes. For a deep dive into the architecture and component responsibilities, refer to the [system design document](../DESIGN.md).

## 1. Prerequisites

Before you start, install the tooling required by the Rust workspace and supporting services:

| Tool | Purpose | Install Notes |
| --- | --- | --- |
| **Rust toolchain (1.82 or newer)** | Builds all workspace crates (edition 2024) | `curl https://sh.rustup.rs -sSf | sh`, then `rustup default stable` |
| **cargo-binutils** *(optional)* | Binary inspection utilities | `rustup component add llvm-tools-preview` then `cargo install cargo-binutils` |
| **SQLx CLI** | Running database migrations locally | `cargo install sqlx-cli --no-default-features --features native-tls,postgres,sqlite` |
| **Docker** *(recommended)* | Quick Postgres sandbox + sandboxed tooling | [Docker install docs](https://docs.docker.com/get-docker/) |
| **Python 3.11+** *(optional)* | Running FastAPI examples | Included with most systems; use `pyenv` or system package manager |

> **Tip:** After installing Rust, run `rustup update` to make sure you have the latest stable toolchain before building Dabgent.

## 2. Environment Configuration

Create a `.env` file at the repository root (or export the variables in your shell) with the credentials and configuration Dabgent expects. The key knobs mirror the configuration listed in the design document, with a few additional provider options.

```bash
# LLM Providers
ANTHROPIC_API_KEY=your_key
GEMINI_API_KEY=your_key
OPENROUTER_API_KEY=your_key
OPENAI_API_KEY=your_key                # Optional, if you plan to target OpenAI-compatible endpoints
DEFAULT_MODEL=claude-3-opus            # See DESIGN.md for architecture context

# Database (PostgreSQL recommended for full MQ experience)
DATABASE_URL=postgresql://user:pass@localhost:5432/dabgent

# Sandbox execution
SANDBOX_TYPE=local                     # or `dagger` when pointing at a Dagger engine
SANDBOX_TIMEOUT=30                     # Seconds before cancelling sandboxed jobs

# Observability
RUST_LOG=dabgent=debug
```

Additional optional knobs supported by the message queue and sandbox crates can be set in a `dabgent.toml` file. The [configuration section of the design document](../DESIGN.md#7-configuration) documents all available keys.

## 3. Database & Sandbox Setup

### PostgreSQL via Docker

```bash
docker run --name dabgent-postgres \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=pass \
  -e POSTGRES_DB=dabgent \
  -p 5432:5432 \
  -d postgres:16
```

Run migrations for both the message queue and application tables:

```bash
# Message queue migrations
cd dabgent/dabgent_mq
sqlx migrate run --database-url "$DATABASE_URL"
cd ../..
```

SQLite is also supported by the MQ crate; use `sqlite:dabgent.db` as your `DATABASE_URL` if you prefer an embedded store during early prototyping.

### Sandbox

The sandbox defaults to local process execution. To exercise the containerized workflow described in the design document, start a Dagger engine (Docker Desktop ships with one) and set:

```bash
SANDBOX_TYPE=dagger
DAGGER_SESSION_PORT=8080   # Example; match your local engine
```

## 4. Building & Running Entry Points

The workspace exposes several entry points that cover CLI usage, service APIs, and supporting daemons. Each command should be run from the repository root unless otherwise noted.

| Component | Command | Purpose |
| --- | --- | --- |
| **CLI** | `cargo run -p dabgent_cli -- --help` | Interactive terminal client for orchestrating tasks |
| **Agent core tests** | `cargo test -p dabgent_agent` | Validates planners, processors, and LLM integrations |
| **Message queue service** | `cargo run -p dabgent_mq` | Starts the event sourcing service; ensure `DATABASE_URL` is set |
| **Sandbox worker** | `cargo run -p dabgent_sandbox` | Handles sandboxed tool execution requests |
| **FastAPI bridge** | `cargo run -p dabgent_fastapi` | Exposes REST entry points for external orchestration |
| **Integrations examples** | `cargo run -p dabgent_integrations --example <name>` | Try Databricks or Google Sheets integrations |

> The high-level interaction between these binaries is illustrated in [Section 3 of the design document](../DESIGN.md#3-core-components-design).

## 5. Recommended Development Workflow

1. **Sync tooling** – Install/update dependencies listed above, then run `cargo check` to ensure the workspace compiles.
2. **Configure secrets** – Populate `.env` with the API keys and service URLs you need for the providers you plan to exercise.
3. **Start dependencies** – Boot Postgres (or SQLite) and the sandbox engine if required.
4. **Run the CLI or services** – Use the commands in Section 4 to launch the binaries relevant to your change.
5. **Write tests** – Prefer colocated unit tests inside each crate. Use `cargo test -p <crate>` to focus on specific components.
6. **Lint & format** – Execute `cargo fmt` and `cargo clippy --workspace --all-targets` before submitting a PR.

## 6. Next Steps

- Explore `dabgent/dabgent_agent/src` to understand how pipelines and processors are wired to the LLM clients.
- Review `dabgent/dabgent_mq/README.md` for deeper details on the event store abstractions.
- Consult `dabgent/DESIGN.md` whenever you need architectural context or sequence diagrams beyond what is summarized here.

Happy hacking!
