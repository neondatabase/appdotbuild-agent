#!/usr/bin/env python3
"""
Compare MLflow evaluation runs.

This script queries MLflow to compare multiple evaluation runs,
showing metrics trends and identifying improvements/regressions.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import mlflow
from mlflow.tracking import MlflowClient


def setup_mlflow() -> MlflowClient:
    """Setup MLflow connection."""
    host = os.environ.get('DATABRICKS_HOST')
    token = os.environ.get('DATABRICKS_TOKEN')

    if not host or not token:
        print("❌ Error: DATABRICKS_HOST or DATABRICKS_TOKEN not set")
        sys.exit(1)

    if not host.startswith('https://'):
        host = f'https://{host}'

    mlflow.set_tracking_uri("databricks")
    os.environ['DATABRICKS_HOST'] = host
    os.environ['DATABRICKS_TOKEN'] = token

    return MlflowClient()


def get_recent_runs(client: MlflowClient, experiment_name: str, n: int = 10) -> List[Any]:
    """Get recent runs from an experiment."""
    try:
        experiment = client.get_experiment_by_name(experiment_name)
        if not experiment:
            print(f"❌ Experiment '{experiment_name}' not found")
            return []

        runs = client.search_runs(
            experiment_ids=[experiment.experiment_id],
            order_by=["start_time DESC"],
            max_results=n
        )

        return runs
    except Exception as e:
        print(f"❌ Error fetching runs: {e}")
        return []


def format_metric(value: float, metric_name: str) -> str:
    """Format metric value for display."""
    if 'rate' in metric_name or 'score' in metric_name:
        return f"{value:.2%}" if value <= 1 else f"{value:.2f}"
    else:
        return f"{value:.2f}"


def compare_runs(runs: List[Any]):
    """Compare multiple runs and display metrics."""
    if not runs:
        print("No runs to compare")
        return

    print("\n" + "=" * 100)
    print("MLflow Evaluation Run Comparison")
    print("=" * 100)

    # Get all unique metrics across runs
    all_metrics = set()
    for run in runs:
        all_metrics.update(run.data.metrics.keys())

    # Sort metrics for consistent display
    metrics_list = sorted(all_metrics)

    # Print header
    print(f"\n{'Run Name':<40} {'Mode':<15} {'Date':<20}")
    print("-" * 100)

    for run in runs:
        run_name = run.data.tags.get('run_name', run.info.run_id[:8])
        mode = run.data.params.get('mode', 'N/A')
        start_time = datetime.fromtimestamp(run.info.start_time / 1000).strftime('%Y-%m-%d %H:%M:%S')

        print(f"{run_name:<40} {mode:<15} {start_time:<20}")

    # Print metrics comparison
    print("\n" + "=" * 100)
    print("Metrics Comparison")
    print("=" * 100)

    print(f"\n{'Metric':<40}", end='')
    for i, run in enumerate(runs):
        run_name = run.data.tags.get('run_name', run.info.run_id[:8])[:12]
        print(f"{run_name:>12}", end='')
    print()
    print("-" * (40 + 12 * len(runs)))

    for metric in metrics_list:
        print(f"{metric:<40}", end='')
        for run in runs:
            value = run.data.metrics.get(metric, 0)
            formatted = format_metric(value, metric)
            print(f"{formatted:>12}", end='')
        print()

    # Calculate trends (compare latest vs previous)
    if len(runs) >= 2:
        print("\n" + "=" * 100)
        print("Latest vs Previous Run")
        print("=" * 100)

        latest = runs[0]
        previous = runs[1]

        print(f"\nLatest:   {latest.data.tags.get('run_name', latest.info.run_id[:8])}")
        print(f"Previous: {previous.data.tags.get('run_name', previous.info.run_id[:8])}")
        print()

        print(f"{'Metric':<40} {'Latest':>12} {'Previous':>12} {'Change':>12}")
        print("-" * 100)

        for metric in metrics_list:
            latest_value = latest.data.metrics.get(metric, 0)
            previous_value = previous.data.metrics.get(metric, 0)

            if previous_value != 0:
                change = ((latest_value - previous_value) / previous_value) * 100
                change_str = f"{change:+.1f}%"
            else:
                change_str = "N/A"

            print(f"{metric:<40} {format_metric(latest_value, metric):>12} "
                  f"{format_metric(previous_value, metric):>12} {change_str:>12}")


def compare_by_mode(runs: List[Any]):
    """Compare runs grouped by mode."""
    print("\n" + "=" * 100)
    print("Comparison by Mode")
    print("=" * 100)

    # Group runs by mode
    by_mode: Dict[str, List[Any]] = {}
    for run in runs:
        mode = run.data.params.get('mode', 'unknown')
        if mode not in by_mode:
            by_mode[mode] = []
        by_mode[mode].append(run)

    # Get all unique metrics
    all_metrics = set()
    for run in runs:
        all_metrics.update(run.data.metrics.keys())
    metrics_list = sorted(all_metrics)

    # Calculate averages by mode
    print(f"\n{'Metric':<40}", end='')
    for mode in sorted(by_mode.keys()):
        print(f"{mode:>15}", end='')
    print()
    print("-" * (40 + 15 * len(by_mode)))

    for metric in metrics_list:
        print(f"{metric:<40}", end='')
        for mode in sorted(by_mode.keys()):
            mode_runs = by_mode[mode]
            values = [run.data.metrics.get(metric, 0) for run in mode_runs]
            avg = sum(values) / len(values) if values else 0
            formatted = format_metric(avg, metric)
            print(f"{formatted:>15}", end='')
        print()


def main():
    """Main function."""
    print("🔍 MLflow Evaluation Run Comparison")

    # Setup MLflow
    client = setup_mlflow()

    # Get recent runs
    experiment_name = "/Shared/klaudbiusz-evaluations"
    print(f"\nFetching runs from experiment: {experiment_name}")

    runs = get_recent_runs(client, experiment_name, n=10)

    if not runs:
        print("No runs found")
        return

    print(f"✓ Found {len(runs)} runs")

    # Compare runs
    compare_runs(runs)

    # Compare by mode
    if len(runs) >= 2:
        compare_by_mode(runs)

    print("\n" + "=" * 100)
    print("✓ Comparison complete")
    print("=" * 100)
    print("\n💡 Tip: View detailed run information in Databricks MLflow UI")
    print(f"   {os.environ.get('DATABRICKS_HOST')}/ml/experiments")


if __name__ == "__main__":
    main()
