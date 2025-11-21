"""
MLflow tracker for evaluation framework.

Tracks evaluation runs, metrics, parameters, and artifacts to monitor
code generation quality over time.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import mlflow
import pandas as pd
from dotenv import load_dotenv
from mlflow.tracking import MlflowClient

# Load environment variables from .env file
load_dotenv()

MLFLOW_EXPERIMENT_NAME = "/Shared/klaudbiusz-evaluations"

class EvaluationTracker:
    """Track evaluation runs and metrics using MLflow."""

    def __init__(self, experiment_name: Optional[str] = None):
        """
        Initialize MLflow tracker.

        Args:
            experiment_name: Name of the MLflow experiment. If not provided,
                           uses MLFLOW_EXPERIMENT_NAME environment variable,
                           or defaults to MLFLOW_EXPERIMENT_NAME
        """
        self.experiment_name = (
            experiment_name or
            os.environ.get('MLFLOW_EXPERIMENT_NAME', MLFLOW_EXPERIMENT_NAME)
        )
        self.client = None
        self.enabled = False
        self._setup_mlflow()

    def _setup_mlflow(self):
        """Configure MLflow connection to Databricks."""
        host = os.environ.get('DATABRICKS_HOST')
        token = os.environ.get('DATABRICKS_TOKEN')

        if not host or not token:
            print("⚠️  MLflow tracking disabled: DATABRICKS_HOST or DATABRICKS_TOKEN not set")
            return

        try:
            # Ensure protocol is present
            if not host.startswith('https://'):
                host = f'https://{host}'

            # Set tracking URI to Databricks
            mlflow.set_tracking_uri("databricks")

            # Configure authentication
            os.environ['DATABRICKS_HOST'] = host
            os.environ['DATABRICKS_TOKEN'] = token

            # Create client
            self.client = MlflowClient()

            # Get or create experiment
            try:
                experiment = self.client.get_experiment_by_name(self.experiment_name)
                if not experiment:
                    self.client.create_experiment(self.experiment_name)
            except Exception:
                self.client.create_experiment(self.experiment_name)

            mlflow.set_experiment(experiment_name=self.experiment_name)

            self.enabled = True
            print(f"✓ MLflow tracking enabled: {self.experiment_name}")

        except Exception as e:
            print(f"⚠️  MLflow setup failed: {e}")
            self.enabled = False

    def start_run(self, run_name: str, tags: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Start a new MLflow run.

        Args:
            run_name: Name for this run
            tags: Optional tags to add

        Returns:
            Run ID or None if tracking is disabled
        """
        if not self.enabled:
            return None

        try:
            run = mlflow.start_run(run_name=run_name)

            # Add default tags
            mlflow.set_tag("framework", "klaudbiusz")
            mlflow.set_tag("run_name", run_name)

            # Add custom tags
            if tags:
                for key, value in tags.items():
                    mlflow.set_tag(key, value)

            return run.info.run_id
        except Exception as e:
            print(f"⚠️  Failed to start MLflow run: {e}")
            return None

    def log_evaluation_parameters(self,
                                  mode: str,
                                  total_apps: int,
                                  timestamp: str,
                                  model_version: Optional[str] = None,
                                  **kwargs):
        """
        Log evaluation parameters.

        Args:
            mode: Generation mode (mcp, vanilla, etc.)
            total_apps: Number of apps evaluated
            timestamp: Evaluation timestamp
            model_version: Claude model version used
            **kwargs: Additional parameters to log
        """
        if not self.enabled:
            return

        try:
            mlflow.log_param("mode", mode)
            mlflow.log_param("total_apps", total_apps)
            mlflow.log_param("timestamp", timestamp)

            if model_version:
                mlflow.log_param("model_version", model_version)

            for key, value in kwargs.items():
                mlflow.log_param(key, value)

        except Exception as e:
            print(f"⚠️  Failed to log parameters: {e}")

    def log_evaluation_metrics(self, evaluation_report: Dict[str, Any]):
        """
        Log evaluation metrics from report.

        Args:
            evaluation_report: Evaluation report dict with summary and metrics
        """
        if not self.enabled:
            return

        try:
            summary = evaluation_report.get('summary', {})

            # Log only top-level aggregate metrics (appeval_100 + 2-3 key metrics)
            total_apps = summary.get('total_apps', 0)
            if total_apps > 0:
                mlflow.log_metric("total_apps", total_apps)

            # Log template distribution metrics
            template_dist = summary.get('template_distribution', {})
            for template_name, count in template_dist.items():
                mlflow.log_metric(f"template_{template_name}_count", count)

            # Log average scores from individual apps
            apps = evaluation_report.get('apps', [])
            if apps:
                # Average appeval_100 composite score (PRIMARY METRIC)
                avg_appeval_100 = sum(app['metrics'].get('appeval_100', 0)
                                     for app in apps) / len(apps)
                mlflow.log_metric("avg_appeval_100", avg_appeval_100)

                # Average eff_units efficiency metric (lower is better)
                eff_values = [app['metrics'].get('eff_units') for app in apps
                             if app.get('metrics', {}).get('eff_units') is not None]
                if eff_values:
                    avg_eff_units = sum(eff_values) / len(eff_values)
                    mlflow.log_metric("avg_eff_units", avg_eff_units)

                # Log per-app detailed metrics as MLflow Table
                # Mapping internal names to standard names from Databricks Apps 2.0 spec
                metric_name_mapping = {
                    'local_runability_score': 'runability_score',
                    # Other metrics already match standard or are prefixed appropriately
                }

                app_records = []
                for app in apps:
                    record = {'app_name': app.get('app_name', '')}

                    # Add all metrics
                    metrics = app.get('metrics', {})
                    for key, value in metrics.items():
                        # Apply name mapping if needed
                        mapped_key = metric_name_mapping.get(key, key)
                        # Convert booleans to int for better querying
                        if isinstance(value, bool):
                            record[mapped_key] = int(value)
                        else:
                            record[mapped_key] = value

                    # Add generation metrics with 'gen_' prefix
                    gen_metrics = app.get('generation_metrics', {})
                    for key, value in gen_metrics.items():
                        record[f'gen_{key}'] = value

                    # Add standard aggregate metrics from spec
                    if 'gen_input_tokens' in record and 'gen_output_tokens' in record:
                        record['tokens_used'] = record['gen_input_tokens'] + record['gen_output_tokens']
                    if 'gen_turns' in record:
                        record['agent_turns'] = record['gen_turns']

                    app_records.append(record)

                # Log as table (all detailed metrics available here)
                if app_records:
                    df = pd.DataFrame(app_records)
                    mlflow.log_table(df, "app_metrics.json")

        except Exception as e:
            print(f"⚠️  Failed to log metrics: {e}")

    def log_generation_metrics(self, generation_metrics: Dict[str, Any]):
        """
        Log generation metrics (cost, tokens, turns).

        Args:
            generation_metrics: Dict with cost_usd, tokens, turns, etc.
        """
        if not self.enabled:
            return

        try:
            if 'cost_usd' in generation_metrics:
                mlflow.log_metric("generation_cost_usd", generation_metrics['cost_usd'])

            if 'total_output_tokens' in generation_metrics:
                mlflow.log_metric("total_output_tokens", generation_metrics['total_output_tokens'])

            if 'avg_turns' in generation_metrics:
                mlflow.log_metric("avg_turns_per_app", generation_metrics['avg_turns'])

            # Cost efficiency: apps per dollar
            if 'cost_usd' in generation_metrics and generation_metrics['cost_usd'] > 0:
                apps_per_dollar = generation_metrics.get('total_apps', 0) / generation_metrics['cost_usd']
                mlflow.log_metric("apps_per_dollar", apps_per_dollar)

        except Exception as e:
            print(f"⚠️  Failed to log generation metrics: {e}")

    def log_artifact_file(self, file_path: str, artifact_path: Optional[str] = None):
        """
        Log a file as an artifact.

        Args:
            file_path: Path to file to log
            artifact_path: Optional subdirectory in artifact store
        """
        if not self.enabled:
            return

        try:
            if Path(file_path).exists():
                mlflow.log_artifact(file_path, artifact_path)
        except Exception as e:
            print(f"⚠️  Failed to log artifact {file_path}: {e}")

    def log_artifacts_directory(self, dir_path: str, artifact_path: Optional[str] = None):
        """
        Log an entire directory as artifacts.

        Args:
            dir_path: Path to directory to log
            artifact_path: Optional subdirectory in artifact store
        """
        if not self.enabled:
            return

        try:
            if Path(dir_path).exists():
                mlflow.log_artifacts(dir_path, artifact_path)
        except Exception as e:
            print(f"⚠️  Failed to log artifacts from {dir_path}: {e}")

    def end_run(self, status: str = "FINISHED"):
        """
        End the current MLflow run.

        Args:
            status: Run status (FINISHED, FAILED, KILLED)
        """
        if not self.enabled:
            return

        try:
            mlflow.end_run(status=status)
        except Exception as e:
            print(f"⚠️  Failed to end MLflow run: {e}")

    def compare_runs(self, run_ids: List[str]) -> Dict[str, Any]:
        """
        Compare multiple evaluation runs.

        Args:
            run_ids: List of MLflow run IDs to compare

        Returns:
            Comparison data with metrics for each run
        """
        if not self.enabled or not self.client:
            return {}

        try:
            comparison = {}
            for run_id in run_ids:
                run = self.client.get_run(run_id)
                comparison[run_id] = {
                    "metrics": run.data.metrics,
                    "params": run.data.params,
                    "start_time": run.info.start_time,
                    "end_time": run.info.end_time,
                }
            return comparison
        except Exception as e:
            print(f"⚠️  Failed to compare runs: {e}")
            return {}


# Convenience function for use in evaluation scripts
def track_evaluation(evaluation_report_path: str,
                    mode: str,
                    run_name: Optional[str] = None,
                    generation_metrics_path: Optional[str] = None) -> Optional[str]:
    """
    Track an evaluation run in MLflow.

    Args:
        evaluation_report_path: Path to evaluation_report.json
        mode: Generation mode (mcp, vanilla, etc.)
        run_name: Optional custom run name
        generation_metrics_path: Optional path to generation metrics JSON

    Returns:
        Run ID or None if tracking failed
    """
    # Load evaluation report
    with open(evaluation_report_path, 'r') as f:
        evaluation_report = json.load(f)

    # Create run name if not provided
    if not run_name:
        timestamp = evaluation_report.get('summary', {}).get('timestamp',
                                                             datetime.utcnow().isoformat())
        run_name = f"eval_{mode}_{timestamp}"

    # Initialize tracker
    tracker = EvaluationTracker()

    # Start run
    run_id = tracker.start_run(run_name, tags={"mode": mode})

    if not run_id:
        return None

    # Log parameters
    summary = evaluation_report.get('summary', {})
    tracker.log_evaluation_parameters(
        mode=mode,
        total_apps=summary.get('total_apps', 0),
        timestamp=summary.get('timestamp', ''),
        model_version="claude-sonnet-4-5-20250929"
    )

    # Log evaluation metrics
    tracker.log_evaluation_metrics(evaluation_report)

    # Log generation metrics if available
    if generation_metrics_path and Path(generation_metrics_path).exists():
        with open(generation_metrics_path, 'r') as f:
            generation_metrics = json.load(f)
        tracker.log_generation_metrics(generation_metrics)

    # Log artifacts
    tracker.log_artifact_file(evaluation_report_path)

    # Check for markdown report
    md_report_path = str(Path(evaluation_report_path).parent / "EVALUATION_REPORT.md")
    if Path(md_report_path).exists():
        tracker.log_artifact_file(md_report_path)

    # End run
    tracker.end_run()

    print(f"✓ MLflow run tracked: {run_id}")
    return run_id
