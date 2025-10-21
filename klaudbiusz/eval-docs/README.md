# Evaluation Documentation

This folder contains the complete evaluation framework documentation for Klaudbiusz.

## Core Documents

### [evals.md](evals.md)
**Complete 9-Metric Framework Definition**

The reference guide for all evaluation metrics with:
- Philosophy: objective metrics only
- Full metric definitions (1-9)
- Implementation code examples
- Pass/fail criteria
- Bash commands for each check

### [EVALUATION_METHODOLOGY.md](EVALUATION_METHODOLOGY.md)
**Zero-Bias Evaluation Methodology**

How we eliminate subjective bias from evaluation:
- What we measure vs. don't measure
- Reproducibility requirements
- CSV output schema
- Bias minimization techniques
- Why this matters for AI-generated code

### [DORA_METRICS.md](DORA_METRICS.md)
**DORA Metrics Integration & Agentic DevX**

How our framework enables DORA metrics:
- Current evaluation results
- DORA coverage analysis
- Agentic DevX detailed scoring
- Local runability & deployability explained
- The vision for autonomous deployment

## Quick Navigation

**Looking for evaluation results?** → See root level files:
- `../EVALUATION_REPORT.md` - Latest human-readable report
- `../evaluation_report.json` - Structured data
- `../evaluation_report.csv` - Spreadsheet format

**Want to run evaluations?** → See `../cli/`:
- `evaluate_all.py` - Batch evaluation
- `evaluate_app.py` - Single app evaluation
- `archive_evaluation.sh` - Create archive

**Need quick start?** → See `../README.md`

---

**Last Updated:** October 17, 2025
**Framework Version:** 1.0 (9 metrics, zero-bias)
