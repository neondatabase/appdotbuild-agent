#!/usr/bin/env python3
"""
Agentic evaluation script - uses Claude with bash tools to evaluate apps.

Instead of hardcoded logic, gives Claude a generic prompt and bash tools
to discover how to build, run, test, and evaluate each app.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded environment variables from {env_path}")
except ImportError:
    # python-dotenv not installed, environment variables must be set in shell
    pass


EVAL_PROMPT = """Evaluate all apps in ../app using the evaluation framework in ../eval-docs/evals.md.

For each app:
1. Read its files to understand what it is
2. Try to build and run it
3. Evaluate against the metrics

The evaluation_report.json MUST have this exact structure:
{
  "summary": {
    "timestamp": "2025-10-22T10:55:27Z",
    "total_apps": 20,
    "evaluated": 20,
    "metrics_summary": {
      "build_success": {"pass": 18, "fail": 2},
      "runtime_success": {"pass": 18, "fail": 2},
      "type_safety": {"pass": 0, "fail": 0},
      "tests_pass": {"pass": 0, "fail": 0},
      "databricks_connectivity": {"pass": 18, "fail": 2},
      "ui_renders": {"pass": 0, "fail": 0}
    }
  },
  "apps": [
    {
      "app_name": "app-name",
      "metrics": {
        "build_success": true,
        "runtime_success": true,
        "type_safety": false,
        "tests_pass": false,
        "databricks_connectivity": true,
        "ui_renders": false,
        "local_runability_score": 3.0,
        "deployability_score": 3.0
      }
    }
  ]
}

Save results to evaluation_report.json and EVALUATION_REPORT.md in the project root.
"""


async def main():
    """Run agentic evaluation."""
    print("🤖 Starting evaluation...")

    options = ClaudeAgentOptions(
        permission_mode="bypassPermissions",
        max_turns=100,
    )

    async for _ in query(prompt=EVAL_PROMPT, options=options):
        pass

    print("✅ Done! Check evaluation_report.json and EVALUATION_REPORT.md")


if __name__ == "__main__":
    asyncio.run(main())
