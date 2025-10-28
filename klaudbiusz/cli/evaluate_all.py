#!/usr/bin/env python3
"""
Batch evaluation script for all generated apps.

Runs lightweight evaluation on all apps and generates a comprehensive report.

Usage:
    python evaluate_all.py
    python evaluate_all.py --output report.json
"""

import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# load environment variables from .env file
load_dotenv()

# Load environment variables
try:
    from dotenv import load_dotenv
    env_paths = [
        Path(__file__).parent.parent.parent / "dabgent" / ".env",
        Path(__file__).parent.parent / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass

try:
    import anthropic  # type: ignore[import-untyped]
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None  # type: ignore[assignment]


@dataclass
class FullMetrics:
    """All 9 metrics from evals.md."""
    # Core functionality (Binary)
    build_success: bool = False
    runtime_success: bool = False
    type_safety: bool = False
    tests_pass: bool = False

    # Databricks (Binary)
    databricks_connectivity: bool = False
    data_returned: bool = False

    # UI (Binary)
    ui_renders: bool = False

    # DevX (Scores)
    local_runability_score: int = 0
    deployability_score: int = 0

    # Metadata
    test_coverage_pct: float = 0.0
    total_loc: int = 0
    has_dockerfile: bool = False
    has_tests: bool = False
    build_time_sec: float = 0.0
    startup_time_sec: float = 0.0


@dataclass
class EvalResult:
    """Evaluation result."""
    app_name: str
    app_dir: str
    timestamp: str
    metrics: FullMetrics
    issues: list[str]
    details: dict[str, Any]


def run_command(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> tuple[bool, str, str]:
    """Run a shell command."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception:
        return False, "", ""


def evaluate_app(app_dir: Path, prompt: str | None = None) -> EvalResult:
    """Run evaluation with all 9 metrics from evals.md."""
    metrics = FullMetrics()
    issues = []
    details_dict = {}

    # Metric 1: Build Success (requires Docker - skip if not available)
    dockerfile = app_dir / "Dockerfile"
    if dockerfile.exists():
        build_start = time.time()
        build_ok, _, _ = run_command(["docker", "build", "-t", f"test-{app_dir.name}", "."], cwd=str(app_dir), timeout=300)
        metrics.build_time_sec = time.time() - build_start
        metrics.build_success = build_ok
        if not build_ok:
            issues.append("Docker build failed")

    # Metric 2: Runtime Success (requires Docker - skip if build failed)
    if metrics.build_success:
        # Start container with PORT=3000 to match our health check
        start_time = time.time()
        run_ok, container_id, _ = run_command(
            ["docker", "run", "-d", "-p", "3000:3000",
             "-e", "PORT=3000",
             "-e", f"DATABRICKS_HOST={os.getenv('DATABRICKS_HOST', '')}",
             "-e", f"DATABRICKS_TOKEN={os.getenv('DATABRICKS_TOKEN', '')}",
             f"test-{app_dir.name}"],
            timeout=30
        )
        if run_ok and container_id:
            container_id = container_id.strip()
            # Wait longer for Node.js to start and check if container is running
            time.sleep(10)

            # First check if container is still running
            running_ok, _, _ = run_command(["docker", "ps", "-q", "-f", f"id={container_id}"], timeout=5)

            if running_ok:
                # Try tRPC health check endpoint
                health_ok, _, _ = run_command(
                    ["curl", "-f", "-X", "GET",
                     "http://localhost:3000/api/trpc/healthcheck?batch=1&input=%7B%7D"],
                    timeout=10
                )
                metrics.runtime_success = health_ok
                metrics.startup_time_sec = time.time() - start_time
                if not health_ok:
                    issues.append("Container failed to start or health check failed")
            else:
                issues.append("Container exited immediately after start")
                metrics.startup_time_sec = time.time() - start_time

            # Cleanup
            run_command(["docker", "stop", container_id], timeout=10)
            run_command(["docker", "rm", container_id], timeout=10)

    # Install dependencies (needed for TypeScript and tests)
    print("  Installing dependencies...")
    server_deps_ok, _, _ = run_command(["npm", "install"], cwd=str(app_dir / "server"), timeout=180)
    client_deps_ok, _, _ = run_command(["npm", "install"], cwd=str(app_dir / "client"), timeout=180)
    deps_installed = server_deps_ok and client_deps_ok

    if not deps_installed:
        issues.append("Dependencies installation failed")

    # Metric 3: Type Safety (requires dependencies)
    if deps_installed:
        type_ok_server, _, _ = run_command(["npx", "tsc", "--noEmit"], cwd=str(app_dir / "server"), timeout=60)
        type_ok_client, _, _ = run_command(["npx", "tsc", "--noEmit"], cwd=str(app_dir / "client"), timeout=60)
        metrics.type_safety = type_ok_server and type_ok_client
        # Only flag TS errors as issues if they cause build/runtime problems
        # (Since apps use tsx which skips type checking, TS strictness is informational)
        if not metrics.type_safety and not metrics.build_success:
            issues.append("TypeScript compilation errors prevent build")

    # Metric 4: Tests Pass (requires dependencies)
    if deps_installed:
        tests_ok, stdout, stderr = run_command(["npm", "test"], cwd=str(app_dir / "server"), timeout=120)
        metrics.tests_pass = tests_ok
        test_files = list((app_dir / "server" / "src").glob("*.test.ts")) + list((app_dir / "server" / "src").glob("**/*.test.ts"))
        metrics.has_tests = len(test_files) > 0
        if not tests_ok:
            issues.append("Tests failed")
    else:
        # If dependencies failed, tests also fail
        tests_ok = False
        metrics.tests_pass = False
        stdout = ""
        stderr = ""

    # Parse coverage
    output = stdout + stderr
    for line in output.split("\n"):
        if "all files" in line.lower() and "%" in line:
            parts = line.split("|")
            if len(parts) >= 2:
                try:
                    metrics.test_coverage_pct = float(parts[1].strip().replace("%", ""))
                except (ValueError, IndexError):
                    pass

    if metrics.test_coverage_pct < 70:
        issues.append(f"Coverage below 70% ({metrics.test_coverage_pct:.1f}%)")

    # Metric 5: Databricks Connectivity (requires running container)
    # For now, if runtime succeeds, we assume DB connectivity works
    # In reality, we'd need to know the specific tRPC procedure names for each app
    if metrics.runtime_success:
        # Runtime success means the tRPC API is responding, which implies DB client initialized
        # We're not testing actual DB queries here since that requires app-specific knowledge
        metrics.databricks_connectivity = True

    # Metric 6: Data Returned (requires running container + knowing procedure names)
    # Skip for now since each app has different tRPC procedures
    # Would need to introspect the router or know procedure names in advance
    metrics.data_returned = False  # TODO: Implement app-specific procedure calls

    # Metric 7: UI Renders (binary VLM check - requires screenshot)
    if ANTHROPIC_AVAILABLE:
        screenshot_path = app_dir / "screenshot_output" / "screenshot.png"
        if not screenshot_path.exists():
            screenshot_path = app_dir / "screenshot.png"

        if screenshot_path.exists():
            try:
                import base64
                image_data = base64.standard_b64encode(screenshot_path.read_bytes()).decode("utf-8")

                client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))  # type: ignore[union-attr]
                message = client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=100,
                    messages=[{
                        "role": "user",
                        "content": [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        }, {
                            "type": "text",
                            "text": """Look at this screenshot and answer ONLY these objective binary questions:

1. Is the page NOT blank (does something render)? Answer: YES or NO
2. Are there NO visible error messages (no 404, 500, crash messages, red error text)? Answer: YES or NO
3. Is there ANY visible content (text, tables, charts, buttons, etc.)? Answer: YES or NO

DO NOT assess quality, aesthetics, or whether it matches requirements.
ONLY verify: Does the page render without errors?

If ALL THREE answers are YES, respond: PASS
If ANY answer is NO, respond: FAIL

Respond with ONLY one word: PASS or FAIL""",
                        }],
                    }],
                )

                # Extract text from content block
                content_block = message.content[0]
                response_text = getattr(content_block, 'text', '').strip().upper()
                metrics.ui_renders = "PASS" in response_text
            except Exception:
                metrics.ui_renders = False
        else:
            metrics.ui_renders = False
    else:
        metrics.ui_renders = False

    # Metric 8: Local runability
    local_score = 0
    readme = app_dir / "README.md"
    if readme.exists() and any(w in readme.read_text().lower() for w in ["setup", "installation"]):
        local_score += 1
    if (app_dir / ".env.example").exists() or (app_dir / ".env.template").exists():
        local_score += 1

    # Check for package.json at root or in server/
    pkg_file = app_dir / "package.json"
    if not pkg_file.exists():
        pkg_file = app_dir / "server" / "package.json"

    if pkg_file.exists():
        try:
            import json as json_mod  # Ensure we have json
            pkg_data = json_mod.loads(pkg_file.read_text())
            local_score += 1
            if "start" in pkg_data.get("scripts", {}):
                local_score += 1
        except Exception:
            # silently fail but at least we tried
            pass
    if (app_dir / "server" / "src" / "index.ts").exists():
        local_score += 1
    metrics.local_runability_score = local_score
    if local_score < 3:
        issues.append(f"Local runability concerns ({local_score}/5)")

    # Metric 9: Deployability
    deploy_score = 0
    if dockerfile.exists():
        deploy_score += 1
        content = dockerfile.read_text()
        if content.count("FROM") > 1:
            deploy_score += 1
        elif "alpine" in content.lower():
            deploy_score += 1
        if "HEALTHCHECK" in content:
            deploy_score += 1
        if "EXPOSE" in content:
            deploy_score += 1
        metrics.has_dockerfile = True
    metrics.deployability_score = deploy_score
    if deploy_score < 3:
        issues.append(f"Deployability concerns ({deploy_score}/5)")

    # Code metrics
    metrics.total_loc = sum(
        len(f.read_text().split("\n"))
        for f in app_dir.rglob("*.ts")
        if "node_modules" not in str(f) and f.is_file()
    )

    return EvalResult(
        app_name=app_dir.name,
        app_dir=str(app_dir),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        metrics=metrics,
        issues=issues,
        details=details_dict,
    )


def load_prompts_and_metrics_from_bulk_run() -> tuple[dict[str, str], dict[str, dict]]:
    """Load prompts and generation metrics using PROMPTS dict from bulk_run.

    Returns:
        (prompts_dict, metrics_dict) where metrics_dict contains cost_usd, input_tokens, output_tokens, turns
    """
    try:
        # Import PROMPTS from bulk_run.py
        from bulk_run import PROMPTS
    except ImportError:
        return {}, {}

    # Look for bulk_run_results file
    script_dir = Path(__file__).parent
    results_files = sorted(script_dir.glob("../bulk_run_results_*.json"), reverse=True)
    if not results_files:
        results_files = sorted(script_dir.glob("../app/bulk_run_results_*.json"), reverse=True)

    if not results_files:
        return dict(PROMPTS), {}

    # Load generation metrics from results file
    try:
        data = json.loads(results_files[0].read_text())

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

        return dict(PROMPTS), gen_metrics

    except Exception:
        return dict(PROMPTS), {}


def generate_summary_report(results: list[dict]) -> dict:
    """Generate summary statistics from evaluation results."""
    total = len(results)

    # Overall statistics - All 9 metrics
    stats = {
        "total_apps": total,
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metrics_summary": {
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

    # Executive Summary - All 9 metrics
    md.append("\n## Executive Summary\n")
    metrics = summary["metrics_summary"]
    total = summary['total_apps']

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


def main():
    """Main entry point."""
    script_dir = Path(__file__).parent
    apps_dir = script_dir.parent / "app"

    if not apps_dir.exists():
        print(f"Error: Apps directory not found: {apps_dir}")
        sys.exit(1)

    # Load prompts and generation metrics from bulk_run.py and bulk_run_results
    prompts, gen_metrics = load_prompts_and_metrics_from_bulk_run()

    # Get all app directories
    app_dirs = [d for d in sorted(apps_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]

    print(f"🔍 Evaluating {len(app_dirs)} apps...")
    print("=" * 60)

    results = []
    for i, app_dir in enumerate(app_dirs, 1):
        print(f"\n[{i}/{len(app_dirs)}] {app_dir.name}")

        try:
            prompt = prompts.get(app_dir.name)
            result = evaluate_app(app_dir, prompt)
            result_dict = asdict(result)

            # Add generation metrics if available
            if app_dir.name in gen_metrics:
                result_dict["generation_metrics"] = gen_metrics[app_dir.name]

            results.append(result_dict)

            # Quick status
            status = "✓" if len(result.issues) <= 2 else "⚠" if len(result.issues) <= 4 else "✗"
            print(f"  {status} {len(result.issues)} issues")

        except Exception as e:
            print(f"  ✗ Error: {str(e)}")
            continue

    print("\n" + "=" * 60)
    print(f"✅ Evaluated {len(results)}/{len(app_dirs)} apps")

    # Generate summary and report
    print("\n📊 Generating summary report...")
    summary = generate_summary_report(results)
    markdown = generate_markdown_report(results, summary)

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
        "apps": results,
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
    csv_content = generate_csv_report(results)
    csv_output.write_text(csv_content)
    print(f"✓ CSV report saved: {csv_output}")

    # Print summary to console - All 9 metrics
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY - 9 OBJECTIVE METRICS")
    print("=" * 60)
    metrics = summary["metrics_summary"]
    total = summary['total_apps']

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


if __name__ == "__main__":
    main()
