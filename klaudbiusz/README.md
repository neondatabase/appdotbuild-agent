# Klaudbiusz

AI-powered Databricks application generator with objective evaluation framework. Uses Claude Agent SDK and OpenCode backends with skills-based tool discovery.

## Overview

Klaudbiusz generates production-ready Databricks applications from natural language prompts and evaluates them using 9 objective, zero-bias metrics. This enables autonomous deployment workflows where AI-generated code can be automatically validated and deployed without human review.

**Current Results:** 90% of generated apps (18/20) are production-ready and deployable.

## Quick Start

### Setup Environment

Create a `.env` file in the `klaudbiusz/` directory (copy from `.env.example`):

```bash
cd klaudbiusz
cp .env.example .env
# Edit .env with your credentials
```

### Generate Applications

Generation runs inside Dagger containers for isolation and reproducibility.

**Prerequisites:**
- Docker running
- Databricks CLI OAuth configured (`~/.databrickscfg` + `~/.databricks/token-cache.json`)
- Skills installed in `~/.claude/skills/` (for Claude backend) or `~/.config/opencode/skills/` (for OpenCode backend)

```bash
cd klaudbiusz

# make sure app folder is empty
cli/archive_evaluation.sh
cli/cleanup_evaluation.sh

# Generate a single app via Dagger (Claude backend - default)
uv run cli/generation/single_run.py "Create a customer churn analysis dashboard"

# Generate with OpenCode backend
uv run cli/generation/single_run.py "Create a customer churn analysis dashboard" --backend=opencode

# Batch generate from prompts
uv run cli/generation/bulk_run.py

# Batch with OpenCode backend
uv run cli/generation/bulk_run.py --backend=opencode

# OpenCode with custom model
uv run cli/generation/bulk_run.py --backend=opencode --model=anthropic/claude-opus-4-5-20251101
```

### Local Debugging (without Dagger)

For faster iteration during development, run directly on host:

```bash
# Local run (Claude backend only)
uv run python -m cli.generation.local_run "Create a dashboard"
```

### Evaluate Generated Apps

```bash
cd klaudbiusz

# Evaluate all apps
uv run cli/evaluation/evaluate_all.py

# Parallel evaluation (faster for large batches)
uv run cli/evaluation/evaluate_all.py -j 4                         # Run 4 evaluations in parallel
uv run cli/evaluation/evaluate_all.py -j 0                         # Auto-detect CPU count
uv run cli/evaluation/evaluate_all.py --parallel 8                 # Long form

# Partial evaluation (filter apps)
uv run cli/evaluation/evaluate_all.py --limit 5                    # First 5 apps
uv run cli/evaluation/evaluate_all.py --apps app1 app2             # Specific apps
uv run cli/evaluation/evaluate_all.py --pattern "customer*"        # Pattern matching
uv run cli/evaluation/evaluate_all.py --skip 10 --limit 5          # Skip first 10, evaluate next 5
uv run cli/evaluation/evaluate_all.py --start-from app5            # Start from specific app

# Custom directory
uv run cli/evaluation/evaluate_all.py --dir /path/to/apps          # Evaluate apps in custom directory

# Staging environment (for testing)
uv run cli/evaluation/evaluate_all.py --staging                    # Log to staging MLflow experiment

# Evaluate single app
uv run cli/evaluation/evaluate_app.py ../app/customer-churn-analysis
```

**Results are automatically logged to MLflow:** Navigate to `ML → Experiments → /Shared/klaudbiusz-evaluations` in Databricks UI / Googfooding.

**Performance:** Parallel evaluation with `-j` can provide 3-4x speedup for large batches (e.g., 20 apps in 5 min vs 15+ min sequential).

## Evaluation Framework

We use **9 objective metrics** to measure autonomous deployability:

| Category | Metrics | Current Results |
|----------|---------|----------------|
| **Core Functionality** | Build, Runtime, Type Safety, Tests | 90%, 90%, 0%, 0% |
| **Databricks Integration** | DB Connectivity, Data Returned | 90%, 0% |
| **UI** | UI Renders | 0% |
| **Agentic DevX** | Local Runability, Deployability | 3.0/5, 3.0/5 |

**See [eval-docs/evals.md](eval-docs/evals.md) for complete metric definitions.**

### MLflow Integration

**Track evaluation quality over time** using Databricks Managed MLflow:

- 📊 **Automatic Tracking**: Every evaluation run logged to MLflow
- 📈 **Metrics Trends**: Monitor success rates, quality scores, cost efficiency
- 🔍 **Run Comparison**: Compare evaluation runs and track improvements
- 📦 **Artifacts**: All reports automatically saved and versioned

### Key Innovation: Agentic DevX

We measure **whether an AI agent can autonomously run and deploy the code** with zero configuration:

- **Local Runability:** Can run with `npm install && npm start`? (3.0/5)
- **Deployability:** Can deploy with `docker build && docker run`? (3.0/5)

**See [eval-docs/DORA_METRICS.md](eval-docs/DORA_METRICS.md) for detailed agentic evaluation approach.**

## Documentation

### Framework & Methodology
- **[eval-docs/evals.md](eval-docs/evals.md)** - Complete 9-metric framework definition
- **[eval-docs/EVALUATION_METHODOLOGY.md](eval-docs/EVALUATION_METHODOLOGY.md)** - Zero-bias evaluation methodology
- **[eval-docs/DORA_METRICS.md](eval-docs/DORA_METRICS.md)** - DORA metrics integration & agentic DevX

### Results (Generated by Evaluation)
- **EVALUATION_REPORT.md** - Latest evaluation results (root level)
- **evaluation_report.json** - Structured data (root level)
- **evaluation_report.csv** - Spreadsheet format (root level)

### Archives
- **klaudbiusz_evaluation_*.tar.gz** - Historical evaluation archives
- **App.build Evals 2.0.docx** - Executive summary

## Project Structure

```
klaudbiusz/
├── README.md                        # This file
├── eval-docs/                       # Evaluation framework docs
│   ├── evals.md                    # 9-metric definitions
│   ├── EVALUATION_METHODOLOGY.md   # Zero-bias methodology
│   └── DORA_METRICS.md             # DORA & agentic DevX
├── app/                             # Generated applications (gitignored)
├── cli/                             # Generation & evaluation scripts
│   ├── generation/                 # App generation
│   │   ├── prompts/               # Prompt collections
│   │   ├── codegen.py             # Claude Agent SDK backend
│   │   ├── dagger_run.py          # Dagger container orchestration
│   │   ├── container_runner.py    # Runner script (inside container or local)
│   │   ├── single_run.py          # Single app generation (via Dagger)
│   │   ├── bulk_run.py            # Batch app generation (via Dagger)
│   │   └── screenshot.py          # Batch screenshotting
│   ├── generation_opencode/        # OpenCode backend (TypeScript)
│   │   └── src/                   # TypeScript source
│   ├── evaluation/                 # App evaluation
│   │   ├── evaluate_all.py        # Batch evaluation
│   │   ├── evaluate_app.py        # Single app evaluation (legacy)
│   │   ├── evaluate_app_dagger.py # Dagger-based evaluation
│   │   ├── eval_checks.py         # Check functions
│   │   └── eval_metrics.py        # Metric definitions
│   ├── utils/                      # Shared utilities
│   ├── analyze_trajectories.py     # Get LLM recommendations
│   ├── archive_evaluation.sh       # Create evaluation archive
│   └── cleanup_evaluation.sh       # Clean generated apps
├── EVALUATION_REPORT.md            # Latest results (gitignored)
├── evaluation_report.json          # Latest data (gitignored)
├── evaluation_report.csv           # Latest spreadsheet (gitignored)
└── klaudbiusz_evaluation_*.tar.gz  # Archives
```

## Workflows

### Development Workflow

1. Write natural language prompt
2. Generate: `uv run cli/generation/single_run.py "your prompt"` or `uv run cli/generation/bulk_run.py`
3. Evaluate: `uv run cli/evaluation/evaluate_all.py -j 0` (parallel, auto-detect CPUs)
4. Review: `cat EVALUATION_REPORT.md`
5. Deploy apps that pass checks

### AI Assisted Edda Improvement Workflow

1. Generate many apps with `uv run cli/generation/bulk_run.py`
2. Analyze the trajectories with `uv run cli/analyze_trajectories.py`
3. Based on the report, improve Edda tools and scaffolding
4. Rerun the evaluation to measure impact

### Archive & Clean Workflow

```bash
# Create archive of apps + reports
./cli/archive_evaluation.sh

# Verify checksum
shasum -a 256 -c klaudbiusz_evaluation_*.tar.gz.sha256

# Clean up generated apps
./cli/cleanup_evaluation.sh
```

## Requirements

- Python 3.12+
- uv (Python package manager)
- Docker (for Dagger containerized evaluations)
- Node.js 18+ (for generated apps)
- Databricks workspace with access token

## Environment Variables

**Recommended:** Use a `.env` file in the `klaudbiusz/` directory:

```bash
# Required for generation and MLflow tracking
DATABRICKS_HOST=https://your-workspace.databricks.com
DATABRICKS_TOKEN=dapi...
ANTHROPIC_API_KEY=sk-ant-...
MLFLOW_EXPERIMENT_NAME=/Shared/klaudbiusz-evaluations

# Optional for logging
DATABASE_URL=postgresql://...
```

All scripts automatically load `.env` if present. Copy `.env.example` to get started:
```bash
cp .env.example .env
```

Alternatively, you can export environment variables manually:
```bash
export DATABRICKS_HOST=https://your-workspace.databricks.com
export DATABRICKS_TOKEN=dapi...
export ANTHROPIC_API_KEY=sk-ant-...
```

## Core Principle

> If an AI agent cannot autonomously deploy its own generated code, that code is not production-ready.

All metrics are **objective, reproducible, and automatable** - no subjective quality assessments.

**See [eval-docs/EVALUATION_METHODOLOGY.md](eval-docs/EVALUATION_METHODOLOGY.md) for our zero-bias philosophy.**

## License

Apache 2.0

---

**Latest Evaluation:** October 17, 2025
**Success Rate:** 90% deployment-ready (18/20 apps)
**Lead Time:** 6-9 minutes (prompt → production-ready code)
