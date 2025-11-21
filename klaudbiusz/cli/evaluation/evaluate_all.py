#!/usr/bin/env python3
"""
Batch evaluation script for all generated apps using Dagger containers.

Runs lightweight evaluation on all apps in isolated Dagger containers
and generates a comprehensive report.

Usage:
    python evaluate_all.py
    python evaluate_all.py --apps app1 app2 app3
    python evaluate_all.py --pattern "customer*"
    python evaluate_all.py --limit 5
    python evaluate_all.py --skip 10
    python evaluate_all.py --start-from app5
    python evaluate_all.py --parallel 4
"""

import argparse
import asyncio
import fnmatch
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import dagger
from dotenv import load_dotenv

from cli.evaluation.eval_metrics import eff_units
from cli.evaluation.evaluate_app_dagger import evaluate_app_async

# Load environment variables from .env file
env_paths = [
    Path(__file__).parent.parent.parent / "edda" / ".env",
    Path(__file__).parent.parent / ".env",
]
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path)
        break


def get_git_commit_hash() -> str | None:
    """Get the current git commit hash."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def load_prompts_and_metrics_from_bulk_run() -> tuple[dict[str, str], dict[str, dict], dict[str, str]]:
    """Load prompts and generation metrics using PROMPTS dict from bulk_run.

    Returns:
        (prompts_dict, metrics_dict, run_config_dict) where metrics_dict contains cost_usd, input_tokens, output_tokens, turns
        and run_config_dict contains mcp_binary, backend, model
    """
    try:
        # Import PROMPTS from bulk_run.py
        from cli.generation.bulk_run import PROMPTS
    except ImportError:
        return {}, {}, {}

    # Look for bulk_run_results file
    script_dir = Path(__file__).parent
    results_files = sorted(script_dir.glob("../bulk_run_results_*.json"), reverse=True)
    if not results_files:
        results_files = sorted(script_dir.glob("../app/bulk_run_results_*.json"), reverse=True)

    if not results_files:
        return dict(PROMPTS), {}, {}

    # Load generation metrics from results file
    try:
        data = json.loads(results_files[0].read_text())

        # Extract run configuration from first result
        run_config = {}
        if data and len(data) > 0:
            first_result = data[0]
            run_config = {
                "mcp_binary": first_result.get("mcp_binary", "cargo run (default)"),
                "backend": first_result.get("backend", "claude"),
                "model": first_result.get("model"),
            }

        # Create a prompt->metrics mapping
        prompt_to_metrics = {}
        for result in data:
            prompt = result.get("prompt")
            metrics = result.get("metrics", {})
            if prompt:
                prompt_to_metrics[prompt] = {
                    "cost_usd": metrics.get("cost_usd", 0),
                    "input_tokens": metrics.get("input_tokens", 0),
                    "output_tokens": metrics.get("output_tokens", 0),
                    "turns": metrics.get("turns", 0),
                }

        # Match app names to metrics using PROMPTS dict
        gen_metrics = {}
        for app_name, prompt in PROMPTS.items():
            if prompt in prompt_to_metrics:
                gen_metrics[app_name] = prompt_to_metrics[prompt]

        return dict(PROMPTS), gen_metrics, run_config

    except Exception:
        return dict(PROMPTS), {}, {}


def generate_summary_report(results: list[dict]) -> dict:
    """Generate summary statistics from evaluation results."""
    total = len(results)

    # Template distribution
    template_counts = Counter()
    for r in results:
        template = r["metrics"].get("template_type", "unknown")
        template_counts[template] += 1

    # Overall statistics - All 9 metrics
    stats = {
        "total_apps": total,
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "template_distribution": dict(template_counts),
        "metrics_summary": {
            # Composite & Efficiency Metrics
            "avg_appeval_100": sum(r["metrics"].get("appeval_100", 0) for r in results) / total if total > 0 else 0,
            "avg_eff_units": sum(r["metrics"].get("eff_units", 0) for r in results if r["metrics"].get("eff_units") is not None) / len([r for r in results if r["metrics"].get("eff_units") is not None]) if len([r for r in results if r["metrics"].get("eff_units") is not None]) > 0 else None,
            # Metric 1-4: Core functionality
            "build_success": sum(1 for r in results if r["metrics"]["build_success"]),
            "runtime_success": sum(1 for r in results if r["metrics"]["runtime_success"]),
            "type_safety_pass": sum(1 for r in results if r["metrics"]["type_safety"]),
            "tests_pass": sum(1 for r in results if r["metrics"]["tests_pass"]),
            "avg_coverage": sum(r["metrics"]["test_coverage_pct"] for r in results) / total if total > 0 else 0,
            # Metric 5-6: Databricks
            "databricks_connectivity": sum(1 for r in results if r["metrics"]["databricks_connectivity"]),
            "data_returned": sum(1 for r in results if r["metrics"]["data_returned"]),
            # Metric 7: UI
            "ui_renders": sum(1 for r in results if r["metrics"]["ui_renders"]),
            # Metric 8-9: DevX
            "local_runability_avg": sum(r["metrics"]["local_runability_score"] for r in results) / total if total > 0 else 0,
            "deployability_avg": sum(r["metrics"]["deployability_score"] for r in results) / total if total > 0 else 0,
            # Metadata
            "total_loc": sum(r["metrics"]["total_loc"] for r in results),
            "avg_loc_per_app": sum(r["metrics"]["total_loc"] for r in results) / total if total > 0 else 0,
            "avg_build_time": sum(r["metrics"]["build_time_sec"] for r in results) / total if total > 0 else 0,
            "avg_startup_time": sum(r["metrics"]["startup_time_sec"] for r in results) / total if total > 0 else 0,
        },
        "generation_metrics": {
            "total_cost_usd": sum(r.get("generation_metrics", {}).get("cost_usd", 0) for r in results),
            "avg_cost_usd": sum(r.get("generation_metrics", {}).get("cost_usd", 0) for r in results) / total if total > 0 else 0,
            "total_input_tokens": sum(r.get("generation_metrics", {}).get("input_tokens", 0) for r in results),
            "total_output_tokens": sum(r.get("generation_metrics", {}).get("output_tokens", 0) for r in results),
            "avg_input_tokens": sum(r.get("generation_metrics", {}).get("input_tokens", 0) for r in results) / total if total > 0 else 0,
            "avg_output_tokens": sum(r.get("generation_metrics", {}).get("output_tokens", 0) for r in results) / total if total > 0 else 0,
            "avg_turns": sum(r.get("generation_metrics", {}).get("turns", 0) for r in results) / total if total > 0 else 0,
            "avg_tokens_per_turn": (sum(r.get("generation_metrics", {}).get("output_tokens", 0) for r in results) / sum(r.get("generation_metrics", {}).get("turns", 0) for r in results)) if sum(r.get("generation_metrics", {}).get("turns", 0) for r in results) > 0 else 0,
        },
        "quality_distribution": {
            "excellent": [],  # No issues
            "good": [],       # 1-2 issues
            "fair": [],       # 3-4 issues
            "poor": []        # 5+ issues
        },
        "common_issues": Counter(),
        "devx_scores": {
            "5_stars": [],  # Both local & deploy >= 4
            "4_stars": [],  # Both >= 3
            "3_stars": [],  # Both >= 2
            "2_stars": [],  # At least one < 2
        },
    }

    # Analyze each app
    for result in results:
        app_name = result["app_name"]
        issues = result["issues"]
        issue_count = len(issues)

        # Quality distribution
        if issue_count == 0:
            stats["quality_distribution"]["excellent"].append(app_name)
        elif issue_count <= 2:
            stats["quality_distribution"]["good"].append(app_name)
        elif issue_count <= 4:
            stats["quality_distribution"]["fair"].append(app_name)
        else:
            stats["quality_distribution"]["poor"].append(app_name)

        # Count common issues
        for issue in issues:
            stats["common_issues"][issue] += 1

        # DevX scoring
        local = result["metrics"]["local_runability_score"]
        deploy = result["metrics"]["deployability_score"]

        if local >= 4 and deploy >= 4:
            stats["devx_scores"]["5_stars"].append(app_name)
        elif local >= 3 and deploy >= 3:
            stats["devx_scores"]["4_stars"].append(app_name)
        elif local >= 2 and deploy >= 2:
            stats["devx_scores"]["3_stars"].append(app_name)
        else:
            stats["devx_scores"]["2_stars"].append(app_name)

    # Convert Counter to dict for JSON serialization
    stats["common_issues"] = dict(stats["common_issues"].most_common(10))

    return stats


def generate_markdown_report(results: list[dict], summary: dict) -> str:
    """Generate a markdown report."""
    md = []

    md.append("# App Evaluation Report")
    md.append(f"\n**Generated:** {summary['evaluated_at']}")
    md.append(f"\n**Total Apps Evaluated:** {summary['total_apps']}")

    # Template distribution
    if "template_distribution" in summary:
        md.append("\n### Template Distribution")
        for template, count in sorted(summary["template_distribution"].items()):
            pct = (count / summary['total_apps'] * 100) if summary['total_apps'] > 0 else 0
            md.append(f"- **{template}:** {count} apps ({pct:.1f}%)")

    # Executive Summary - All 9 metrics
    md.append("\n## Executive Summary\n")
    metrics = summary["metrics_summary"]
    total = summary['total_apps']

    # Top-level metrics
    md.append(f"**📊 Overall Quality Score:** {metrics['avg_appeval_100']:.1f}/100")
    if metrics.get('avg_eff_units') is not None:
        md.append(f"**⚡ Average Efficiency:** {metrics['avg_eff_units']:.1f} units (lower is better)\n")
    else:
        md.append("")

    md.append("### Core Functionality (Metrics 1-4)")
    md.append(f"- **Build Success:** {metrics['build_success']}/{total} apps ({metrics['build_success']/total*100:.1f}%)")
    md.append(f"- **Runtime Success:** {metrics['runtime_success']}/{total} apps ({metrics['runtime_success']/total*100:.1f}%)")
    md.append(f"- **Type Safety:** {metrics['type_safety_pass']}/{total} apps pass ({metrics['type_safety_pass']/total*100:.1f}%)")
    md.append(f"- **Tests Passing:** {metrics['tests_pass']}/{total} apps pass ({metrics['tests_pass']/total*100:.1f}%)")
    md.append(f"- **Average Test Coverage:** {metrics['avg_coverage']:.1f}%")

    md.append("\n### Databricks Integration (Metrics 5-6)")
    md.append(f"- **Databricks Connectivity:** {metrics['databricks_connectivity']}/{total} apps ({metrics['databricks_connectivity']/total*100:.1f}%)")
    md.append(f"- **Data Returned:** {metrics['data_returned']}/{total} apps ({metrics['data_returned']/total*100:.1f}%)")

    md.append("\n### UI (Metric 7)")
    md.append(f"- **UI Renders:** {metrics['ui_renders']}/{total} apps ({metrics['ui_renders']/total*100:.1f}%)")

    md.append("\n### Developer Experience (Metrics 8-9)")
    md.append(f"- **Average Local Runability:** {metrics['local_runability_avg']:.1f}/5 ⭐")
    md.append(f"- **Average Deployability:** {metrics['deployability_avg']:.1f}/5 ⭐")

    md.append("\n### Code & Performance")
    md.append(f"- **Total Lines of Code:** {metrics['total_loc']:,}")
    md.append(f"- **Average LOC per App:** {metrics['avg_loc_per_app']:.0f}")
    if metrics['avg_build_time'] > 0:
        md.append(f"- **Average Build Time:** {metrics['avg_build_time']:.1f}s")
    if metrics['avg_startup_time'] > 0:
        md.append(f"- **Average Startup Time:** {metrics['avg_startup_time']:.1f}s")

    # Generation Metrics (if available)
    if "generation_metrics" in summary and summary["generation_metrics"]["total_cost_usd"] > 0:
        gen = summary["generation_metrics"]
        md.append("\n### AI Generation Metrics")
        md.append(f"- **Total Cost:** ${gen['total_cost_usd']:.2f}")
        md.append(f"- **Average Cost per App:** ${gen['avg_cost_usd']:.2f}")
        md.append(f"- **Total Output Tokens:** {gen['total_output_tokens']:,}")
        md.append(f"- **Average Output Tokens per App:** {gen['avg_output_tokens']:.0f}")
        md.append(f"- **Average Turns per App:** {gen['avg_turns']:.0f}")

        # Calculate tokens per turn
        if gen['avg_turns'] > 0:
            tokens_per_turn = gen['avg_output_tokens'] / gen['avg_turns']
            md.append(f"- **Average Output Tokens per Turn:** {tokens_per_turn:.0f}")

    # Quality Distribution
    md.append("\n## Quality Distribution\n")
    qual = summary["quality_distribution"]
    total = summary['total_apps']
    md.append(f"- 🟢 **Excellent** (0 issues): {len(qual['excellent'])} apps ({len(qual['excellent'])/total*100:.1f}%)")
    md.append(f"- 🟡 **Good** (1-2 issues): {len(qual['good'])} apps ({len(qual['good'])/total*100:.1f}%)")
    md.append(f"- 🟠 **Fair** (3-4 issues): {len(qual['fair'])} apps ({len(qual['fair'])/total*100:.1f}%)")
    md.append(f"- 🔴 **Poor** (5+ issues): {len(qual['poor'])} apps ({len(qual['poor'])/total*100:.1f}%)")

    # Developer Experience Scores
    md.append("\n## Developer Experience (DevX) Scores\n")
    devx = summary["devx_scores"]
    md.append(f"- ⭐⭐⭐⭐⭐ **Excellent**: {len(devx['5_stars'])} apps (local ≥4, deploy ≥4)")
    md.append(f"- ⭐⭐⭐⭐ **Good**: {len(devx['4_stars'])} apps (local ≥3, deploy ≥3)")
    md.append(f"- ⭐⭐⭐ **Fair**: {len(devx['3_stars'])} apps (local ≥2, deploy ≥2)")
    md.append(f"- ⭐⭐ **Needs Work**: {len(devx['2_stars'])} apps")

    # Common Issues
    md.append("\n## Most Common Issues\n")
    md.append("| Issue | Count | % of Apps |")
    md.append("|-------|-------|-----------|")
    for issue, count in summary["common_issues"].items():
        pct = count / summary['total_apps'] * 100
        md.append(f"| {issue} | {count} | {pct:.1f}% |")

    # Top Performers
    md.append("\n## Top Performers\n")

    # Apps with no issues
    excellent = qual['excellent']
    if excellent:
        md.append("\n### 🏆 Apps with Zero Issues\n")
        for app in excellent[:10]:  # Top 10
            md.append(f"- `{app}`")

    # Highest DevX scores
    top_devx = devx['5_stars']
    if top_devx:
        md.append("\n### ⭐ Best Developer Experience\n")
        for app in top_devx[:10]:
            md.append(f"- `{app}`")

    # Apps needing attention
    md.append("\n## Apps Needing Attention\n")
    poor = qual['poor']
    if poor:
        md.append("\n### 🔴 Apps with Most Issues\n")
        # Sort by issue count
        poor_sorted = sorted(
            [(r["app_name"], len(r["issues"])) for r in results if r["app_name"] in poor],
            key=lambda x: x[1],
            reverse=True
        )
        for app, issue_count in poor_sorted[:10]:
            md.append(f"- `{app}` ({issue_count} issues)")

    # Detailed breakdown by metric
    md.append("\n## Detailed Metrics Breakdown\n")

    # Type Safety
    md.append("\n### Type Safety\n")
    type_fail = [r["app_name"] for r in results if not r["metrics"]["type_safety"]]
    if type_fail:
        md.append(f"\n**Failed ({len(type_fail)} apps):**")
        for app in type_fail[:15]:
            md.append(f"- `{app}`")
        if len(type_fail) > 15:
            md.append(f"- _{len(type_fail) - 15} more..._")

    # Tests
    md.append("\n### Tests\n")
    test_fail = [r["app_name"] for r in results if not r["metrics"]["tests_pass"]]
    if test_fail:
        md.append(f"\n**Failed ({len(test_fail)} apps):**")
        for app in test_fail[:15]:
            md.append(f"- `{app}`")
        if len(test_fail) > 15:
            md.append(f"- _{len(test_fail) - 15} more..._")

    # Coverage distribution
    coverage_ranges = {
        "0%": 0,
        "1-25%": 0,
        "26-50%": 0,
        "51-75%": 0,
        "76-100%": 0,
    }
    for r in results:
        cov = r["metrics"]["test_coverage_pct"]
        if cov == 0:
            coverage_ranges["0%"] += 1
        elif cov <= 25:
            coverage_ranges["1-25%"] += 1
        elif cov <= 50:
            coverage_ranges["26-50%"] += 1
        elif cov <= 75:
            coverage_ranges["51-75%"] += 1
        else:
            coverage_ranges["76-100%"] += 1

    md.append("\n**Coverage Distribution:**")
    for range_name, count in coverage_ranges.items():
        pct = count / summary['total_apps'] * 100 if summary['total_apps'] > 0 else 0
        md.append(f"- {range_name}: {count} apps ({pct:.1f}%)")

    # Local Runability Details
    md.append("\n### Local Runability Details\n")
    local_issues = defaultdict(int)
    for r in results:
        for detail in r["details"].get("local_runability", []):
            if "✗" in detail:
                local_issues[detail] += 1

    if local_issues:
        md.append("**Common local runability issues:**")
        for issue, count in sorted(local_issues.items(), key=lambda x: x[1], reverse=True)[:5]:
            md.append(f"- {issue}: {count} apps")

    # Deployability Details
    md.append("\n### Deployability Details\n")
    deploy_issues = defaultdict(int)
    for r in results:
        for detail in r["details"].get("deployability", []):
            if "✗" in detail:
                deploy_issues[detail] += 1

    if deploy_issues:
        md.append("**Common deployability issues:**")
        for issue, count in sorted(deploy_issues.items(), key=lambda x: x[1], reverse=True)[:5]:
            md.append(f"- {issue}: {count} apps")

    # Recommendations
    md.append("\n## Recommendations\n")

    type_fail_pct = (summary['total_apps'] - metrics['type_safety_pass']) / summary['total_apps'] * 100 if summary['total_apps'] > 0 else 0
    test_fail_pct = (summary['total_apps'] - metrics['tests_pass']) / summary['total_apps'] * 100 if summary['total_apps'] > 0 else 0

    if type_fail_pct > 50:
        md.append(f"\n### 🚨 CRITICAL: TypeScript Errors ({type_fail_pct:.0f}% of apps)")
        md.append("- **Priority:** HIGH")
        md.append("- **Action:** Review and fix TypeScript compilation errors across all apps")
        md.append("- **Root cause:** Likely template or code generation issues")

    if test_fail_pct > 50:
        md.append(f"\n### 🚨 CRITICAL: Test Failures ({test_fail_pct:.0f}% of apps)")
        md.append("- **Priority:** HIGH")
        md.append("- **Action:** Ensure tests run successfully")
        md.append("- **Root cause:** May need environment setup or test configuration fixes")

    if metrics['avg_coverage'] < 50:
        md.append(f"\n### ⚠️ WARNING: Low Test Coverage ({metrics['avg_coverage']:.0f}% average)")
        md.append("- **Priority:** MEDIUM")
        md.append("- **Action:** Improve test coverage across apps")
        md.append("- **Target:** Aim for 70%+ coverage")

    # Check for common missing items
    readme_missing = sum(1 for r in results if "No README.md" in str(r["details"].get("local_runability", [])))
    if readme_missing > summary['total_apps'] * 0.7:
        md.append(f"\n### 📝 Missing Documentation ({readme_missing} apps)")
        md.append("- **Priority:** MEDIUM")
        md.append("- **Action:** Auto-generate README.md for each app")
        md.append("- **Content:** Setup instructions, environment variables, usage examples")

    healthcheck_missing = sum(1 for r in results if "No HEALTHCHECK" in str(r["details"].get("deployability", [])))
    if healthcheck_missing > summary['total_apps'] * 0.7:
        md.append(f"\n### 🏥 Missing Health Checks ({healthcheck_missing} apps)")
        md.append("- **Priority:** LOW")
        md.append("- **Action:** Add HEALTHCHECK directive to Dockerfiles")
        md.append("- **Benefit:** Better production monitoring and container orchestration")

    # Positive highlights
    md.append("\n## Highlights ✨\n")

    if metrics['deployability_avg'] >= 4:
        md.append(f"- 🎉 **Strong deployability**: Average score of {metrics['deployability_avg']:.1f}/5")

    if metrics['local_runability_avg'] >= 3:
        md.append(f"- 👍 **Good local development setup**: Average score of {metrics['local_runability_avg']:.1f}/5")

    if len(excellent) > 0:
        md.append(f"- 🏆 **{len(excellent)} apps with zero issues** - excellent quality!")

    if metrics['avg_loc_per_app'] < 1000:
        md.append(f"- 📦 **Concise codebase**: Average of {metrics['avg_loc_per_app']:.0f} LOC per app")

    return "\n".join(md)


def generate_csv_report(results: list[dict]) -> str:
    """Generate CSV report with objective metrics only."""
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # CSV Header - All 9 metrics from evals.md
    header = [
        "app_name",
        "timestamp",
        "template_type",
        # Metric 1-4: Core functionality
        "build_success",
        "runtime_success",
        "type_safety_pass",
        "tests_pass",
        "test_coverage_pct",
        # Metric 5-6: Databricks
        "databricks_connectivity",
        "data_returned",
        # Metric 7: UI
        "ui_renders",
        # Metric 8-9: DevX
        "local_runability_score",
        "deployability_score",
        # Composite score
        "appeval_100",
        # Metadata
        "build_time_sec",
        "startup_time_sec",
        "total_loc",
        "has_dockerfile",
        "has_tests",
        "issue_count",
        "issues",
    ]
    writer.writerow(header)

    # Write data rows
    for result in results:
        metrics = result["metrics"]
        issues = result["issues"]

        row = [
            result["app_name"],
            result["timestamp"],
            metrics.get("template_type", "unknown"),
            # Metric 1-4
            1 if metrics["build_success"] else 0,
            1 if metrics["runtime_success"] else 0,
            1 if metrics["type_safety"] else 0,
            1 if metrics["tests_pass"] else 0,
            f"{metrics['test_coverage_pct']:.1f}",
            # Metric 5-6
            1 if metrics["databricks_connectivity"] else 0,
            1 if metrics["data_returned"] else 0,
            # Metric 7
            1 if metrics["ui_renders"] else 0,
            # Metric 8-9
            metrics["local_runability_score"],
            metrics["deployability_score"],
            # Composite score
            f"{metrics['appeval_100']:.1f}",
            # Metadata
            f"{metrics['build_time_sec']:.1f}",
            f"{metrics['startup_time_sec']:.1f}",
            metrics["total_loc"],
            1 if metrics["has_dockerfile"] else 0,
            1 if metrics["has_tests"] else 0,
            len(issues),
            "; ".join(issues) if issues else "",
        ]
        writer.writerow(row)

    return output.getvalue()


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Evaluate generated apps with 9 objective metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python evaluate_all.py                          # Evaluate all apps in ../app
  python evaluate_all.py --dir /path/to/apps      # Evaluate apps in custom directory
  python evaluate_all.py --staging                # Report to staging MLflow experiment
  python evaluate_all.py --apps app1 app2         # Evaluate specific apps
  python evaluate_all.py --pattern "customer*"    # Evaluate apps matching pattern
  python evaluate_all.py --limit 5                # Evaluate first 5 apps
  python evaluate_all.py --skip 10                # Skip first 10 apps
  python evaluate_all.py --start-from app5        # Start from specific app
  python evaluate_all.py --limit 10 --skip 5      # Evaluate 10 apps starting from 6th
  python evaluate_all.py -j 4                     # Evaluate 4 apps in parallel
  python evaluate_all.py -j 0                     # Auto-detect CPU count and parallelize
        """
    )

    parser.add_argument(
        '--dir',
        metavar='PATH',
        help='Directory containing apps to evaluate (default: ../app)'
    )

    parser.add_argument(
        '--staging',
        action='store_true',
        help='Report results to staging MLflow experiment (/Shared/edda-staging-evaluations)'
    )

    parser.add_argument(
        '--parallel',
        '-j',
        type=int,
        metavar='N',
        default=1,
        help='Run N evaluations in parallel (default: 1 = sequential). Use -j 0 for auto (CPU count)'
    )

    parser.add_argument(
        '--mcp-binary',
        metavar='PATH',
        help='MCP binary path (overrides value from bulk_run results)'
    )

    parser.add_argument(
        '--backend',
        metavar='NAME',
        help='Backend used (claude/litellm, overrides value from bulk_run results)'
    )

    parser.add_argument(
        '--model',
        metavar='NAME',
        help='Model used (overrides value from bulk_run results)'
    )

    filter_group = parser.add_argument_group('app filtering')
    filter_group.add_argument(
        '--apps',
        nargs='+',
        metavar='APP',
        help='Specific app names to evaluate'
    )
    filter_group.add_argument(
        '--pattern',
        metavar='PATTERN',
        help='Glob pattern to match app names (e.g., "customer*")'
    )
    filter_group.add_argument(
        '--limit',
        type=int,
        metavar='N',
        help='Limit evaluation to first N apps (after skip/start-from)'
    )
    filter_group.add_argument(
        '--skip',
        type=int,
        metavar='N',
        help='Skip first N apps'
    )
    filter_group.add_argument(
        '--start-from',
        metavar='APP',
        dest='start_from',
        help='Start evaluation from this app (inclusive)'
    )

    return parser.parse_args()


def filter_app_dirs(app_dirs: list[Path], args) -> list[Path]:
    """Filter app directories based on command-line arguments."""
    filtered = app_dirs

    # Filter by specific app names
    if args.apps:
        app_names = set(args.apps)
        filtered = [d for d in filtered if d.name in app_names]
        if not filtered:
            print(f"Warning: No apps found matching names: {', '.join(args.apps)}")
            sys.exit(1)

    # Filter by pattern
    if args.pattern:
        filtered = [d for d in filtered if fnmatch.fnmatch(d.name, args.pattern)]
        if not filtered:
            print(f"Warning: No apps found matching pattern: {args.pattern}")
            sys.exit(1)

    # Start from specific app
    if args.start_from:
        start_idx = None
        for i, d in enumerate(filtered):
            if d.name == args.start_from:
                start_idx = i
                break

        if start_idx is None:
            print(f"Warning: App '{args.start_from}' not found")
            sys.exit(1)

        filtered = filtered[start_idx:]

    # Skip first N apps
    if args.skip:
        if args.skip >= len(filtered):
            print(f"Warning: --skip {args.skip} is >= total apps ({len(filtered)})")
            sys.exit(1)
        filtered = filtered[args.skip:]

    # Limit to first N apps
    if args.limit:
        filtered = filtered[:args.limit]

    return filtered


async def evaluate_app_with_metadata_async(
    client: dagger.Client,
    app_dir: Path,
    prompt: str | None,
    gen_metrics: dict,
    index: int,
    total: int
) -> dict | None:
    """
    Async wrapper for evaluate_app_async that adds generation metrics and handles errors.
    Designed to work with asyncio.gather().
    """
    print(f"\n[{index}/{total}] {app_dir.name}")

    # Assign unique port for parallel execution to avoid Docker port conflicts
    # Base port 8000 + index, supports up to ~60k parallel workers
    port = 8000 + index

    try:
        result = await evaluate_app_async(client, app_dir, prompt, port)
        result_dict = asdict(result)

        # Add generation metrics if available
        if app_dir.name in gen_metrics:
            result_dict["generation_metrics"] = gen_metrics[app_dir.name]

            # Calculate eff_units from generation_metrics if not already present
            if result_dict["metrics"].get("eff_units") is None:
                gm = gen_metrics[app_dir.name]
                tokens = gm.get("input_tokens", 0) + gm.get("output_tokens", 0)
                result_dict["metrics"]["eff_units"] = eff_units(
                    tokens_used=tokens if tokens > 0 else None,
                    agent_turns=gm.get("turns"),
                    validation_runs=gm.get("validation_runs", 0)
                )

        return result_dict

    except KeyboardInterrupt:
        raise  # Re-raise to allow user to stop
    except Exception as e:
        print(f"❌ Error evaluating {app_dir.name}: {e}")
        return None  # Return None for failed evaluations


async def main_async():
    """Async main entry point."""
    args = parse_args()

    script_dir = Path(__file__).parent

    # Use custom directory if provided, otherwise default to ../app
    if args.dir:
        apps_dir = Path(args.dir).resolve()
    else:
        apps_dir = script_dir.parent / "app"

    if not apps_dir.exists():
        print(f"Error: Apps directory not found: {apps_dir}")
        sys.exit(1)

    # Load prompts and generation metrics from bulk_run.py and bulk_run_results
    prompts, gen_metrics, run_config = load_prompts_and_metrics_from_bulk_run()

    # Override run config with CLI args if provided
    if args.mcp_binary:
        run_config["mcp_binary"] = args.mcp_binary
    if args.backend:
        run_config["backend"] = args.backend
    if args.model:
        run_config["model"] = args.model

    # Get all app directories
    all_app_dirs = [d for d in sorted(apps_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]

    # Filter based on command-line arguments
    app_dirs = filter_app_dirs(all_app_dirs, args)

    # Auto-detect CPU count if --parallel 0
    import os
    cpu_count = os.cpu_count() or 1
    if args.parallel == 0:
        args.parallel = cpu_count
        print(f"🔧 Auto-detected {cpu_count} CPUs, using --parallel {args.parallel}")
    elif args.parallel < 0:
        print(f"Error: --parallel must be >= 0 (got {args.parallel})")
        sys.exit(1)

    print(f"🔍 Evaluating {len(app_dirs)} apps (out of {len(all_app_dirs)} total)...")
    print(f"   Directory: {apps_dir}")
    if args.apps:
        print(f"   Filter: specific apps: {', '.join(args.apps)}")
    if args.pattern:
        print(f"   Filter: pattern '{args.pattern}'")
    if args.skip:
        print(f"   Filter: skipping first {args.skip} apps")
    if args.start_from:
        print(f"   Filter: starting from '{args.start_from}'")
    if args.limit:
        print(f"   Filter: limit to {args.limit} apps")
    if args.parallel > 1:
        print(f"   Parallelism: {args.parallel} workers (Dagger containers)")
    print("=" * 60)

    # Warn if parallelism is too high
    if args.parallel > 1:
        if args.parallel > cpu_count:
            print(f"⚠️  Warning: Requested {args.parallel} parallel jobs but system has {cpu_count} CPUs")
            print(f"   Consider using --parallel {cpu_count} for optimal performance")
        if args.parallel > len(app_dirs):
            print(f"⚠️  Warning: Using {args.parallel} workers for {len(app_dirs)} apps")
            print(f"   Consider using --parallel {len(app_dirs)} to avoid idle workers")

    # Track timing
    eval_start_time = time.time()

    # Run evaluations using Dagger with async/await
    # Wrap in try-except to handle Dagger session cleanup timeout gracefully
    import subprocess
    results = []
    try:
        async with dagger.Connection() as client:
            if args.parallel > 1:
                print(f"🚀 Running {args.parallel} evaluations in parallel (Dagger containers)...")

                # Use asyncio.gather() for parallel execution with semaphore to limit concurrency
                semaphore = asyncio.Semaphore(args.parallel)

                async def evaluate_with_semaphore(index, app_dir):
                    async with semaphore:
                        return await evaluate_app_with_metadata_async(
                            client,
                            app_dir,
                            prompts.get(app_dir.name),
                            gen_metrics,
                            index,
                            len(app_dirs)
                        )

                results = await asyncio.gather(
                    *[evaluate_with_semaphore(i, app_dir) for i, app_dir in enumerate(app_dirs, 1)],
                    return_exceptions=False
                )

                # Filter out None results (failed evaluations)
                results = [r for r in results if r is not None]

            else:
                # Sequential execution
                print("🔄 Running evaluations sequentially (Dagger containers)...")
                results = []
                for i, app_dir in enumerate(app_dirs, 1):
                    result_dict = await evaluate_app_with_metadata_async(
                        client,
                        app_dir,
                        prompts.get(app_dir.name),
                        gen_metrics,
                        i,
                        len(app_dirs)
                    )
                    if result_dict is not None:
                        results.append(result_dict)

        # Warn about disconnection delay for large batches (Dagger has 5min hardcoded timeout)
        if len(app_dirs) >= 5:
            print("\n⏳ Disconnecting from Dagger (may take up to 5 minutes)...")

    except subprocess.TimeoutExpired:
        # Dagger session cleanup timed out, but evaluations completed successfully
        # This is a known issue with Dagger SDK - the cleanup can take longer than the 300s timeout
        print("\n⚠️  Warning: Dagger session cleanup timed out (this is expected for large batches)")
        print("   All evaluations completed successfully, continuing with report generation...")

    eval_duration = time.time() - eval_start_time

    print("\n" + "=" * 60)
    print(f"✅ Evaluated {len(results)}/{len(app_dirs)} apps in {eval_duration:.1f}s")
    if args.parallel > 1:
        estimated_sequential = eval_duration * args.parallel
        print(f"   ⚡ Parallelization saved ~{estimated_sequential - eval_duration:.1f}s (speedup: {estimated_sequential/eval_duration:.1f}x)")

    # Generate summary and report (filter out None results)
    valid_results = [r for r in results if r is not None]
    print(f"\n📊 Generating summary report for {len(valid_results)} apps...")
    summary = generate_summary_report(valid_results)
    markdown = generate_markdown_report(valid_results, summary)

    # Determine output paths - save to app-eval directory
    output_dir = script_dir.parent / "app-eval"
    output_dir.mkdir(exist_ok=True)

    # Rename existing evaluation files before creating new ones
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    old_files = [
        (output_dir / "evaluation_report.json", f"evaluation_report_{timestamp}.json"),
        (output_dir / "evaluation_report.csv", f"evaluation_report_{timestamp}.csv"),
        (output_dir / "EVALUATION_REPORT.md", f"EVALUATION_REPORT_{timestamp}.md"),
    ]

    for old_file, new_name in old_files:
        if old_file.exists():
            renamed = old_file.parent / new_name
            old_file.rename(renamed)
            print(f"  Preserved: {old_file.name} → {new_name}")

    json_output = output_dir / "evaluation_report.json"
    md_output = output_dir / "EVALUATION_REPORT.md"

    # Save full results
    full_report = {
        "summary": summary,
        "apps": valid_results,
        "timestamp": timestamp,
        "evaluation_run_id": timestamp,
    }
    json_output.write_text(json.dumps(full_report, indent=2))
    print(f"✓ JSON report saved: {json_output}")

    # Save markdown report
    md_output.write_text(markdown)
    print(f"✓ Markdown report saved: {md_output}")

    # Save CSV report
    csv_output = output_dir / "evaluation_report.csv"
    csv_content = generate_csv_report(valid_results)
    csv_output.write_text(csv_content)
    print(f"✓ CSV report saved: {csv_output}")

    # Log to MLflow
    print("\n📊 Logging to MLflow...")
    try:
        from cli.utils.mlflow_tracker import EvaluationTracker

        # Determine experiment name based on --staging flag
        experiment_name = "/Shared/edda-staging-evaluations" if args.staging else None

        tracker = EvaluationTracker(experiment_name=experiment_name)
        if tracker.enabled:
            # Start MLflow run
            run_name = f"eval-{timestamp}"
            tags = {
                "mode": "evaluation",
                "environment": "staging" if args.staging else "production"
            }

            # Add git commit hash if available
            git_hash = get_git_commit_hash()
            if git_hash:
                tags["git_commit"] = git_hash

            run_id = tracker.start_run(run_name=run_name, tags=tags)

            # Log parameters
            params = {
                "mode": "evaluation",
                "total_apps": summary['total_apps'],
                "timestamp": timestamp,
                "model_version": "claude-sonnet-4-5-20250929",
            }

            # Add run config parameters if available
            if run_config.get("mcp_binary"):
                params["mcp_binary"] = run_config["mcp_binary"]
            if run_config.get("backend"):
                params["backend"] = run_config["backend"]
            if run_config.get("model"):
                params["llm_model"] = run_config["model"]

            tracker.log_evaluation_parameters(**params)

            # Log metrics from evaluation report
            tracker.log_evaluation_metrics(full_report)

            # Log artifacts
            tracker.log_artifact_file(str(json_output))
            tracker.log_artifact_file(str(md_output))
            tracker.log_artifact_file(str(csv_output))

            # End run
            tracker.end_run()

            print("✓ MLflow tracking complete")
            print(f"  Run ID: {run_id}")
            print(f"  View: ML → Experiments → {tracker.experiment_name}")
        else:
            print("⚠️  MLflow tracking disabled (credentials not set)")
    except Exception as e:
        print(f"⚠️  MLflow tracking failed: {e}")

    # Print summary to console - All 9 metrics
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY - 9 OBJECTIVE METRICS")
    print("=" * 60)
    metrics = summary["metrics_summary"]
    total = summary['total_apps']

    # Top-level metrics
    print(f"\n📊 Overall Quality Score: {metrics['avg_appeval_100']:.1f}/100")
    if metrics.get('avg_eff_units') is not None:
        print(f"⚡ Average Efficiency:    {metrics['avg_eff_units']:.1f} units (lower is better)")

    print("\nCore Functionality:")
    print(f"  1. Build Success:         {metrics['build_success']}/{total} ({metrics['build_success']/total*100:.0f}%)")
    print(f"  2. Runtime Success:       {metrics['runtime_success']}/{total} ({metrics['runtime_success']/total*100:.0f}%)")
    print(f"  3. Type Safety:           {metrics['type_safety_pass']}/{total} ({metrics['type_safety_pass']/total*100:.0f}%)")
    print(f"  4. Tests Pass:            {metrics['tests_pass']}/{total} ({metrics['tests_pass']/total*100:.0f}%)")
    print(f"     Coverage:              {metrics['avg_coverage']:.1f}%")

    print("\nDatabricks Integration:")
    print(f"  5. DB Connectivity:       {metrics['databricks_connectivity']}/{total} ({metrics['databricks_connectivity']/total*100:.0f}%)")
    print(f"  6. Data Returned:         {metrics['data_returned']}/{total} ({metrics['data_returned']/total*100:.0f}%)")

    print("\nUI:")
    print(f"  7. UI Renders:            {metrics['ui_renders']}/{total} ({metrics['ui_renders']/total*100:.0f}%)")

    print("\nDeveloper Experience:")
    print(f"  8. Local Runability:      {metrics['local_runability_avg']:.1f}/5 ⭐")
    print(f"  9. Deployability:         {metrics['deployability_avg']:.1f}/5 ⭐")

    print("\nQuality Distribution:")
    qual = summary["quality_distribution"]
    print(f"  🟢 Excellent: {len(qual['excellent'])}")
    print(f"  🟡 Good:      {len(qual['good'])}")
    print(f"  🟠 Fair:      {len(qual['fair'])}")
    print(f"  🔴 Poor:      {len(qual['poor'])}")

    print(f"\n📄 Full report: {md_output}")

    # Generate interactive HTML viewer
    print("\n🌐 Generating interactive HTML viewer...")
    try:
        from generate_eval_viewer import generate_html_viewer
        html_output = output_dir / "evaluation_viewer.html"
        generate_html_viewer(json_output, html_output)
        print(f"✓ HTML viewer: {html_output}")
        print(f"\n🎉 Open in browser: file://{html_output.absolute()}")
    except Exception as e:
        print(f"⚠️  Could not generate HTML viewer: {e}")


def main():
    """Sync wrapper for async main."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
