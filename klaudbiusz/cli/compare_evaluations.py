#!/usr/bin/env python3
"""Compare two evaluation runs and generate improvement report."""

import json
from pathlib import Path
from datetime import datetime

def load_archive_results():
    """Load old results from archive."""
    # Old dataset results (from archive README)
    return {
        "build_success": 9,
        "runtime_success": 9,
        "type_safety": 0,
        "tests_pass": 0,
        "coverage": 0.0,
        "db_connectivity": 9,
        "local_runability": 3.0,
        "deployability": 2.5,
        "total_apps": 20,
        "avg_build_time": 1.2,
        "avg_startup_time": 4.6,
        "avg_loc": 725,
        "docker_failures": 8,
    }

def load_current_results():
    """Load current results from evaluation_report.json."""
    report_path = Path("../evaluation_report.json")

    with open(report_path) as f:
        data = json.load(f)

    # Calculate metrics
    build_success = sum(1 for app in data["apps"] if app["metrics"]["build_success"])
    runtime_success = sum(1 for app in data["apps"] if app["metrics"]["runtime_success"])
    type_safety = sum(1 for app in data["apps"] if app["metrics"]["type_safety"])
    tests_pass = sum(1 for app in data["apps"] if app["metrics"]["tests_pass"])
    db_connectivity = sum(1 for app in data["apps"] if app["metrics"]["databricks_connectivity"])
    docker_failures = sum(1 for app in data["apps"] if not app["metrics"]["build_success"])

    avg_coverage = sum(app["metrics"]["test_coverage_pct"] for app in data["apps"]) / len(data["apps"])
    avg_runability = sum(app["metrics"]["local_runability_score"] for app in data["apps"]) / len(data["apps"])
    avg_deployability = sum(app["metrics"]["deployability_score"] for app in data["apps"]) / len(data["apps"])
    avg_build_time = sum(app["metrics"]["build_time_sec"] for app in data["apps"]) / len(data["apps"])
    avg_startup_time = sum(app["metrics"]["startup_time_sec"] for app in data["apps"]) / len(data["apps"])
    avg_loc = sum(app["metrics"]["total_loc"] for app in data["apps"]) / len(data["apps"])

    return {
        "build_success": build_success,
        "runtime_success": runtime_success,
        "type_safety": type_safety,
        "tests_pass": tests_pass,
        "coverage": avg_coverage,
        "db_connectivity": db_connectivity,
        "local_runability": avg_runability,
        "deployability": avg_deployability,
        "total_apps": len(data["apps"]),
        "avg_build_time": avg_build_time,
        "avg_startup_time": avg_startup_time,
        "avg_loc": avg_loc,
        "docker_failures": docker_failures,
    }

def calculate_improvement(old_val, new_val, is_percentage=False):
    """Calculate improvement percentage."""
    if old_val == 0:
        return float('inf') if new_val > 0 else 0
    change = ((new_val - old_val) / old_val) * 100
    return change

def generate_comparison_report():
    """Generate markdown comparison report."""
    old = load_archive_results()
    new = load_current_results()

    report = []
    report.append("# Evaluation Comparison Report")
    report.append("")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    report.append("## Overview")
    report.append("")
    report.append("Comparison between:")
    report.append("- **Old Dataset:** October 17, 2025 (archived)")
    report.append("- **New Dataset:** October 17, 2025 (current)")
    report.append("")

    # Core Metrics Comparison
    report.append("## Core Metrics Improvement")
    report.append("")
    report.append("| Metric | Old | New | Change | Improvement |")
    report.append("|--------|-----|-----|--------|-------------|")

    metrics = [
        ("Build Success", "build_success", "/20", True),
        ("Runtime Success", "runtime_success", "/20", True),
        ("Type Safety Pass", "type_safety", "/20", True),
        ("Tests Pass", "tests_pass", "/20", True),
        ("DB Connectivity", "db_connectivity", "/20", True),
        ("Docker Build Failures", "docker_failures", "/20", False),  # Lower is better
    ]

    for label, key, suffix, higher_is_better in metrics:
        old_val = old[key]
        new_val = new[key]
        change = new_val - old_val

        if higher_is_better:
            improvement = "🟢" if change > 0 else ("🔴" if change < 0 else "⚪")
            change_str = f"+{change}" if change > 0 else str(change)
        else:
            improvement = "🟢" if change < 0 else ("🔴" if change > 0 else "⚪")
            change_str = f"{change:+d}"

        old_pct = f"{(old_val/20)*100:.0f}%" if suffix == "/20" else str(old_val)
        new_pct = f"{(new_val/20)*100:.0f}%" if suffix == "/20" else str(new_val)

        report.append(f"| {label} | {old_val}{suffix} ({old_pct}) | {new_val}{suffix} ({new_pct}) | {change_str} | {improvement} |")

    report.append("")

    # DevX Metrics
    report.append("## Developer Experience (DevX) Metrics")
    report.append("")
    report.append("| Metric | Old | New | Change | Improvement |")
    report.append("|--------|-----|-----|--------|-------------|")

    devx_metrics = [
        ("Local Runability", "local_runability", "/5"),
        ("Deployability", "deployability", "/5"),
    ]

    for label, key, suffix in devx_metrics:
        old_val = old[key]
        new_val = new[key]
        change = new_val - old_val
        improvement = "🟢" if change > 0 else ("🔴" if change < 0 else "⚪")

        report.append(f"| {label} | {old_val:.1f}{suffix} | {new_val:.1f}{suffix} | {change:+.1f} | {improvement} |")

    report.append("")

    # Performance Metrics
    report.append("## Performance Metrics")
    report.append("")
    report.append("| Metric | Old | New | Change |")
    report.append("|--------|-----|-----|--------|")

    perf_metrics = [
        ("Avg Build Time", "avg_build_time", "s"),
        ("Avg Startup Time", "avg_startup_time", "s"),
        ("Avg Lines of Code", "avg_loc", " LOC"),
    ]

    for label, key, unit in perf_metrics:
        old_val = old[key]
        new_val = new[key]
        change = new_val - old_val
        change_pct = calculate_improvement(old_val, new_val)

        if unit == "s":
            report.append(f"| {label} | {old_val:.1f}{unit} | {new_val:.1f}{unit} | {change:+.1f}{unit} ({change_pct:+.0f}%) |")
        else:
            report.append(f"| {label} | {old_val:.0f}{unit} | {new_val:.0f}{unit} | {change:+.0f}{unit} ({change_pct:+.0f}%) |")

    report.append("")

    # Key Improvements
    report.append("## Key Improvements 🎉")
    report.append("")

    build_improvement = new["build_success"] - old["build_success"]
    runtime_improvement = new["runtime_success"] - old["runtime_success"]
    deploy_improvement = new["deployability"] - old["deployability"]
    docker_improvement = old["docker_failures"] - new["docker_failures"]

    if build_improvement > 0:
        report.append(f"- **Build Success:** +{build_improvement} apps ({old['build_success']}/20 → {new['build_success']}/20, **+{build_improvement/20*100:.0f}%**)")

    if runtime_improvement > 0:
        report.append(f"- **Runtime Success:** +{runtime_improvement} apps ({old['runtime_success']}/20 → {new['runtime_success']}/20, **+{runtime_improvement/20*100:.0f}%**)")

    if deploy_improvement > 0:
        report.append(f"- **Deployability:** +{deploy_improvement:.1f} points ({old['deployability']:.1f}/5 → {new['deployability']:.1f}/5, **+{deploy_improvement/5*100:.0f}%**)")

    if docker_improvement > 0:
        report.append(f"- **Docker Build Reliability:** {docker_improvement} fewer failures ({old['docker_failures']}/20 → {new['docker_failures']}/20, **-{docker_improvement/old['docker_failures']*100:.0f}%**)")

    report.append("")

    # Summary
    report.append("## Summary")
    report.append("")

    total_improvements = sum([
        1 if build_improvement > 0 else 0,
        1 if runtime_improvement > 0 else 0,
        1 if deploy_improvement > 0 else 0,
        1 if docker_improvement > 0 else 0,
    ])

    if total_improvements >= 3:
        report.append(f"✅ **Significant improvement across {total_improvements}/4 key metrics!**")
    elif total_improvements >= 1:
        report.append(f"⚠️  **Moderate improvement across {total_improvements}/4 key metrics.**")
    else:
        report.append("❌ **No significant improvements detected.**")

    report.append("")
    report.append(f"**Deployment Readiness:** {new['build_success']}/20 apps ({new['build_success']/20*100:.0f}%) can be built and deployed")
    report.append(f"**Production Ready:** {new['runtime_success']}/20 apps ({new['runtime_success']/20*100:.0f}%) successfully run in containers")

    report.append("")
    report.append("---")
    report.append("")
    report.append("**Note:** Type safety and test failures remain at 100% - these are critical blockers for production use.")

    return "\n".join(report)

if __name__ == "__main__":
    report = generate_comparison_report()

    # Save to file
    output_path = Path("../EVALUATION_COMPARISON.md")
    output_path.write_text(report)

    print("✅ Comparison report generated!")
    print(f"   Location: {output_path.absolute()}")
    print("")
    print(report)
