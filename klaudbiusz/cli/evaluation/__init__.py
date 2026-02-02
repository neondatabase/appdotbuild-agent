"""
App evaluation tools.

High-level API for running evaluations:
    from cli.evaluation import run_evaluation_simple

    report = run_evaluation_simple(
        apps_dir="/Volumes/main/default/apps_mcp_generated",
        mlflow_experiment="/Shared/apps-mcp-evaluations",
    )
"""

import asyncio
import time
from pathlib import Path
from typing import Any

from cli.utils.shared import is_databricks_environment


def run_evaluation_simple(
    apps_dir: str | Path,
    mlflow_experiment: str | None = None,
    parallelism: int = 4,
    fast_mode: bool = True,
    no_dagger: bool | None = None,
) -> dict[str, Any]:
    """High-level evaluation entry point.

    Handles:
    - Environment detection (Databricks auto-enables no_dagger)
    - Apps directory discovery (supports UC Volumes with latest.txt)
    - MLflow logging (if experiment provided)

    Args:
        apps_dir: Path to directory containing apps to evaluate.
                  Can be a UC Volume path or local directory.
        mlflow_experiment: Optional MLflow experiment name for logging results.
        parallelism: Number of parallel evaluations (default: 4).
        fast_mode: Skip slow LLM/VLM checks for faster evaluation (default: True).
        no_dagger: Run without any containers (no Dagger, no Docker).
                   Apps with Dockerfiles will be skipped. Auto-detected if None.

    Returns:
        Evaluation report dict with 'summary' and 'apps' keys.

    Example:
        from cli.evaluation import run_evaluation_simple

        report = run_evaluation_simple(
            apps_dir="/Volumes/main/default/apps",
            mlflow_experiment="/Shared/my-evaluations",
        )
        print(f"Evaluated {report['summary']['total_apps']} apps")
        print(f"Average score: {report['summary']['metrics_summary']['avg_appeval_100']}")
    """
    from cli.evaluation.eval_metrics import eff_units
    from cli.evaluation.evaluate_all import (
        generate_summary_report,
        load_prompts_and_metrics_from_bulk_run,
    )
    from cli.utils.apps_discovery import find_latest_apps_dir, list_apps_in_dir

    # Resolve apps directory
    apps_path = Path(apps_dir)
    resolved_path = find_latest_apps_dir(apps_path)
    if resolved_path is None:
        resolved_path = apps_path

    if not resolved_path.exists():
        raise ValueError(f"Apps directory not found: {apps_dir}")

    # Auto-detect Databricks environment
    if no_dagger is None:
        no_dagger = is_databricks_environment()
        if no_dagger:
            print("Databricks environment detected - using Docker CLI mode")

    # Load prompts and generation metrics
    prompts, gen_metrics, _ = load_prompts_and_metrics_from_bulk_run()

    # Get app directories
    app_dirs = list_apps_in_dir(resolved_path)
    if not app_dirs:
        raise ValueError(f"No apps found in: {resolved_path}")

    print(f"Evaluating {len(app_dirs)} apps from {resolved_path}...")

    results: list[dict[str, Any]] = []
    eval_start = time.time()

    if no_dagger:
        from dataclasses import asdict
        from cli.evaluation.evaluate_app import evaluate_app

        # Filter out apps with Dockerfiles (they require Docker)
        docker_apps = [d for d in app_dirs if (d / "Dockerfile").exists()]
        non_docker_apps = [d for d in app_dirs if not (d / "Dockerfile").exists()]

        if docker_apps:
            print(f"Skipping {len(docker_apps)} apps with Dockerfiles (require Docker)")

        if not non_docker_apps:
            raise ValueError("No apps without Dockerfiles found. Use Dagger mode for Docker-based apps.")

        app_dirs = non_docker_apps

        for i, app_dir in enumerate(app_dirs, 1):
            port = 8000 + i
            print(f"[{i}/{len(app_dirs)}] {app_dir.name}")
            try:
                result = evaluate_app(app_dir, prompts.get(app_dir.name), port)
                result_dict = asdict(result)

                # Add generation metrics if available
                import json
                gm = gen_metrics.get(app_dir.name)
                if not gm:
                    metrics_file = app_dir / "generation_metrics.json"
                    if metrics_file.exists():
                        try:
                            gm = json.loads(metrics_file.read_text())
                        except Exception:
                            pass
                if gm:
                    result_dict["generation_metrics"] = gm

                results.append(result_dict)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"Error evaluating {app_dir.name}: {e}")
    else:
        from dataclasses import asdict as asdict_fn
        import dagger
        from cli.evaluation.evaluate_app_dagger import evaluate_app_async

        async def run_dagger_evaluations() -> list[dict[str, Any]]:
            async with dagger.Connection() as client:
                semaphore = asyncio.Semaphore(parallelism)
                dagger_results: list[dict[str, Any]] = []

                async def eval_one(idx: int, app_dir: Path) -> dict[str, Any] | None:
                    async with semaphore:
                        port = 8000 + idx
                        try:
                            result = await evaluate_app_async(
                                client, app_dir, prompts.get(app_dir.name), port, fast_mode=fast_mode
                            )
                            result_dict = asdict_fn(result)
                            if app_dir.name in gen_metrics:
                                result_dict["generation_metrics"] = gen_metrics[app_dir.name]
                                if result_dict["metrics"].get("eff_units") is None:
                                    gm = gen_metrics[app_dir.name]
                                    tokens = gm.get("input_tokens", 0) + gm.get("output_tokens", 0)
                                    result_dict["metrics"]["eff_units"] = eff_units(
                                        tokens_used=tokens if tokens > 0 else None,
                                        agent_turns=gm.get("turns"),
                                        validation_runs=gm.get("validation_runs", 0),
                                    )
                            return result_dict
                        except Exception as e:
                            print(f"Error evaluating {app_dir.name}: {e}")
                            return None

                tasks = [eval_one(i, d) for i, d in enumerate(app_dirs, 1)]
                for result in await asyncio.gather(*tasks):
                    if result is not None:
                        dagger_results.append(result)
                return dagger_results

        # Handle Databricks notebooks where event loop is already running
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()

        results = asyncio.run(run_dagger_evaluations())

    eval_duration = time.time() - eval_start
    print(f"Evaluated {len(results)}/{len(app_dirs)} apps in {eval_duration:.1f}s")

    # Generate summary
    summary = generate_summary_report(results)

    report = {
        "summary": summary,
        "apps": results,
    }

    # Log to MLflow if experiment provided
    if mlflow_experiment:
        from cli.evaluation.tracking import log_evaluation_to_mlflow, setup_mlflow

        if setup_mlflow(mlflow_experiment):
            run_id = log_evaluation_to_mlflow(report)
            if run_id:
                print(f"MLflow run logged: {run_id}")

    return report


__all__ = [
    "run_evaluation_simple",
    "is_databricks_environment",
]
