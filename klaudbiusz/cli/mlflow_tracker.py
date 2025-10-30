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
from mlflow.tracking import MlflowClient


class EvaluationTracker:
    """Track evaluation runs and metrics using MLflow."""

    def __init__(self, experiment_name: str = "/Shared/klaudbiusz-evaluations"):
        """
        Initialize MLflow tracker.

        Args:
            experiment_name: Name of the MLflow experiment
        """
        self.experiment_name = experiment_name
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
                if experiment:
                    experiment_id = experiment.experiment_id
                else:
                    experiment_id = self.client.create_experiment(self.experiment_name)
            except:
                experiment_id = self.client.create_experiment(self.experiment_name)

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
            metrics_summary = summary.get('metrics_summary', {})

            # Log binary metric success rates
            for metric_name, counts in metrics_summary.items():
                # Handle new format: {"pass": X, "fail": Y}
                if isinstance(counts, dict) and 'pass' in counts and 'fail' in counts:
                    total = counts['pass'] + counts['fail']
                    if total > 0:
                        rate = counts['pass'] / total
                        mlflow.log_metric(f"{metric_name}_rate", rate)
                        mlflow.log_metric(f"{metric_name}_pass", counts['pass'])
                        mlflow.log_metric(f"{metric_name}_fail", counts['fail'])

                # Handle old format: "X/Y" or "X/Y (N/A: Z)"
                elif isinstance(counts, str) and '/' in counts:
                    # Parse "X/Y" or "X/Y (N/A: Z)" format
                    parts = counts.split('(')[0].strip().split('/')
                    if len(parts) == 2:
                        try:
                            passed = int(parts[0])
                            total = int(parts[1])
                            failed = total - passed
                            if total > 0:
                                rate = passed / total
                                mlflow.log_metric(f"{metric_name}_rate", rate)
                                mlflow.log_metric(f"{metric_name}_pass", passed)
                                mlflow.log_metric(f"{metric_name}_fail", failed)
                        except ValueError:
                            pass  # Skip if can't parse

                # Handle average scores: "X.XX/5" format
                elif isinstance(counts, str) and '/5' in counts:
                    try:
                        score = float(counts.split('/')[0])
                        mlflow.log_metric(metric_name, score)
                    except ValueError:
                        pass

            # Calculate and log aggregate metrics
            total_apps = summary.get('total_apps', 0)
            if total_apps > 0:
                mlflow.log_metric("total_apps", total_apps)
                mlflow.log_metric("evaluated", summary.get('evaluated', total_apps))

            # Log average scores from individual apps
            apps = evaluation_report.get('apps', [])
            if apps:
                avg_runability = sum(app['metrics'].get('local_runability_score', 0)
                                    for app in apps) / len(apps)
                avg_deployability = sum(app['metrics'].get('deployability_score', 0)
                                       for app in apps) / len(apps)

                mlflow.log_metric("avg_local_runability_score", avg_runability)
                mlflow.log_metric("avg_deployability_score", avg_deployability)

                # Overall quality score (0-1) - handle both formats
                build_pass = 0
                db_pass = 0

                build_metric = metrics_summary.get('build_success', {})
                if isinstance(build_metric, dict):
                    build_pass = build_metric.get('pass', 0)
                elif isinstance(build_metric, str) and '/' in build_metric:
                    try:
                        build_pass = int(build_metric.split('/')[0])
                    except:
                        pass

                db_metric = metrics_summary.get('databricks_connectivity', {})
                if isinstance(db_metric, dict):
                    db_pass = db_metric.get('pass', 0)
                elif isinstance(db_metric, str) and '/' in db_metric:
                    try:
                        db_pass = int(db_metric.split('/')[0])
                    except:
                        pass

                quality_score = (build_pass + db_pass) / (2 * total_apps) if total_apps > 0 else 0
                mlflow.log_metric("overall_quality_score", quality_score)

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
