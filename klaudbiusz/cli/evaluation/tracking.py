"""
Simplified MLflow tracking API for klaudbiusz evaluations.

Provides high-level functions for logging evaluation and generation results
to MLflow without needing to manage runs manually.

Usage:
    from cli.evaluation.tracking import setup_mlflow, log_evaluation_to_mlflow

    # Setup (optional - auto-configures if DATABRICKS_HOST/TOKEN set)
    setup_mlflow("/Shared/my-experiment")

    # Log evaluation results
    run_id = log_evaluation_to_mlflow(evaluation_report, run_name="eval-run-1")
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import mlflow
from dotenv import load_dotenv

load_dotenv()

_mlflow_configured = False
_experiment_name: str | None = None


def _is_on_databricks_cluster() -> bool:
    """Check if running on a Databricks cluster."""
    return os.environ.get("SPARK_HOME") is not None or os.path.exists("/databricks")


def setup_mlflow(
    experiment_name: str,
    tracking_uri: str = "databricks",
) -> bool:
    """Configure MLflow tracking.

    Args:
        experiment_name: MLflow experiment name (e.g., "/Shared/my-evaluations")
        tracking_uri: MLflow tracking URI (default: "databricks")

    Returns:
        True if MLflow is enabled and configured, False otherwise.

    Example:
        if setup_mlflow("/Shared/apps-mcp-evaluations"):
            print("MLflow ready!")
    """
    global _mlflow_configured, _experiment_name

    host = os.environ.get("DATABRICKS_HOST")
    token = os.environ.get("DATABRICKS_TOKEN")

    # On Databricks clusters, use automatic authentication
    if _is_on_databricks_cluster():
        try:
            mlflow.set_tracking_uri(tracking_uri)
            mlflow.set_experiment(experiment_name)
            _experiment_name = experiment_name
            _mlflow_configured = True
            print(f"MLflow tracking enabled (Databricks cluster auto-auth): {experiment_name}")
            return True
        except Exception as e:
            print(f"MLflow setup failed on Databricks cluster: {e}")
            _mlflow_configured = False
            return False

    # Fall back to env var authentication
    if not host or not token:
        print("MLflow tracking disabled: DATABRICKS_HOST or DATABRICKS_TOKEN not set (and not on Databricks cluster)")
        _mlflow_configured = False
        return False

    try:
        if not host.startswith("https://"):
            host = f"https://{host}"
        os.environ["DATABRICKS_HOST"] = host

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment_name)
        _experiment_name = experiment_name
        _mlflow_configured = True
        print(f"MLflow tracking enabled: {experiment_name}")
        return True
    except Exception as e:
        print(f"MLflow setup failed: {e}")
        _mlflow_configured = False
        return False


def is_mlflow_enabled() -> bool:
    """Check if MLflow tracking is enabled."""
    return _mlflow_configured


def log_evaluation_to_mlflow(
    evaluation_report: dict[str, Any],
    run_name: str | None = None,
    tags: dict[str, str] | None = None,
    artifact_paths: list[str] | None = None,
) -> str | None:
    """Log evaluation results to MLflow.

    Args:
        evaluation_report: Evaluation report dict with 'summary' and 'apps' keys.
        run_name: Optional run name. Auto-generated if not provided.
        tags: Optional additional tags to log.
        artifact_paths: Optional list of file paths to log as artifacts.

    Returns:
        Run ID if successful, None otherwise.

    Example:
        report = json.load(open("evaluation_report.json"))
        run_id = log_evaluation_to_mlflow(report, run_name="eval-2024-01-15")
    """
    from cli.utils.mlflow_tracker import EvaluationTracker

    global _experiment_name

    tracker = EvaluationTracker(experiment_name=_experiment_name)
    if not tracker.enabled:
        return None

    summary = evaluation_report.get("summary", {})
    timestamp = summary.get("timestamp", datetime.utcnow().strftime("%Y%m%d_%H%M%S"))

    if not run_name:
        run_name = f"eval_{timestamp}"

    merged_tags = {"mode": "evaluation"}
    if tags:
        merged_tags.update(tags)

    run_id = tracker.start_run(run_name=run_name, tags=merged_tags)
    if not run_id:
        return None

    tracker.log_evaluation_parameters(
        mode="evaluation",
        total_apps=summary.get("total_apps", 0),
        timestamp=timestamp,
    )

    tracker.log_evaluation_metrics(evaluation_report)

    if artifact_paths:
        for path in artifact_paths:
            if Path(path).exists():
                tracker.log_artifact_file(path)

    tracker.end_run()
    return run_id


def log_generation_to_mlflow(
    generation_results: list[dict[str, Any]],
    run_name: str | None = None,
    tags: dict[str, str] | None = None,
) -> str | None:
    """Log generation metrics to MLflow.

    Args:
        generation_results: List of generation result dicts with metrics.
        run_name: Optional run name. Auto-generated if not provided.
        tags: Optional additional tags to log.

    Returns:
        Run ID if successful, None otherwise.

    Example:
        results = [
            {"app_name": "app1", "success": True, "cost_usd": 0.05, "tokens": 5000},
            {"app_name": "app2", "success": True, "cost_usd": 0.04, "tokens": 4500},
        ]
        run_id = log_generation_to_mlflow(results, run_name="gen-batch-1")
    """
    from cli.utils.mlflow_tracker import EvaluationTracker

    global _experiment_name

    tracker = EvaluationTracker(experiment_name=_experiment_name)
    if not tracker.enabled:
        return None

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    if not run_name:
        run_name = f"gen_{timestamp}"

    merged_tags = {"mode": "generation"}
    if tags:
        merged_tags.update(tags)

    run_id = tracker.start_run(run_name=run_name, tags=merged_tags)
    if not run_id:
        return None

    total_apps = len(generation_results)
    successful = sum(1 for r in generation_results if r.get("success", False))
    total_cost = sum(r.get("cost_usd", 0) or 0 for r in generation_results)
    total_tokens = sum(r.get("tokens", 0) or 0 for r in generation_results)
    total_turns = sum(r.get("turns", 0) or 0 for r in generation_results)

    mlflow.log_param("total_apps", total_apps)
    mlflow.log_param("timestamp", timestamp)

    mlflow.log_metric("successful_apps", successful)
    mlflow.log_metric("failed_apps", total_apps - successful)
    mlflow.log_metric("success_rate", successful / total_apps if total_apps > 0 else 0)
    mlflow.log_metric("total_cost_usd", total_cost)
    mlflow.log_metric("avg_cost_usd", total_cost / total_apps if total_apps > 0 else 0)
    mlflow.log_metric("total_tokens", total_tokens)
    mlflow.log_metric("avg_tokens", total_tokens / total_apps if total_apps > 0 else 0)
    mlflow.log_metric("avg_turns", total_turns / total_apps if total_apps > 0 else 0)

    tracker.end_run()
    return run_id


__all__ = [
    "setup_mlflow",
    "is_mlflow_enabled",
    "log_evaluation_to_mlflow",
    "log_generation_to_mlflow",
]
