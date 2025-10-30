# Evaluation Documentation

Complete evaluation framework documentation for Klaudbiusz.

## Getting Started

**New to evaluations?** → Start with **[evals.md](evals.md)**

Quick start:
```bash
./verify_agent_integration.sh  # Verify setup
./run_eval_with_env.sh         # Run evaluation
```

## Documentation Index

### Core Framework

**[evals.md](evals.md)** - Complete implementation guide
- 9-metric framework definitions
- Usage guide and available scripts
- Environment setup and configuration
- MLflow tracking integration
- Cost estimates and runtime expectations
- Troubleshooting

### Methodology & Design

**[EVALUATION_METHODOLOGY.md](EVALUATION_METHODOLOGY.md)** - Zero-bias methodology
- Design philosophy and principles
- Agentic evaluation approach
- Agent SDK integration details (PATH fix, environment loading)
- Reproducibility and objectivity
- Bias minimization for AI code

**[DORA_METRICS.md](DORA_METRICS.md)** - DORA metrics integration
- Lead time, deployment frequency, MTTR, CFR
- How evaluation metrics support DORA
- Gaps and future enhancements

## File Organization

All evaluation documentation **must** be in this directory. **DO NOT** create evaluation docs in the root.

Evaluation scripts remain in repo root for execution:
- `run_eval_with_env.sh` - Run evaluation with proper environment loading
- `run_vanilla_eval.sh` - Full pipeline for Vanilla SDK mode
- `run_mcp_eval.sh` - Full pipeline for MCP mode
- `run_all_evals.sh` - Run both evaluations sequentially
- `verify_agent_integration.sh` - Verify agent SDK integration

---

**Last Updated:** October 24, 2025
**Framework:** v2.0 (Direct + VLM + Agent-based metrics)
