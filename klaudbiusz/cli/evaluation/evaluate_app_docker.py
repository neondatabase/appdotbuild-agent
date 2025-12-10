#!/usr/bin/env python3
"""Docker-based evaluation script for generated Databricks apps (no Dagger).

Uses plain Docker CLI to run evaluations in isolated containers.
Useful for environments that have Docker but not Dagger (e.g., Databricks Jobs).
"""

import time
from dataclasses import asdict
from pathlib import Path

from cli.evaluation.eval_metrics import calculate_appeval_100
from cli.evaluation.evaluate_app import (
    EvalResult,
    FullMetrics,
    check_data_validity_llm,
    check_databricks_connectivity,
    check_deployability,
    check_local_runability,
    check_ui_functional_vlm,
)
from cli.utils.template_detection import detect_template
from cli.utils.ts_workspace_docker import (
    build_app,
    check_runtime,
    check_types,
    create_ts_workspace_docker,
    install_dependencies,
    run_tests,
)


def evaluate_app_docker(
    app_dir: Path,
    prompt: str | None = None,
    port: int = 8000,
    fast_mode: bool = False,
) -> EvalResult:
    """Run full evaluation on an app using Docker CLI.

    Args:
        app_dir: Path to the app directory
        prompt: Optional prompt used to generate the app
        port: Port to use for the app (unique per parallel execution)
        fast_mode: Skip slow LLM/VLM checks (DB connectivity, data validity, UI renders)

    Returns:
        EvalResult with metrics
    """
    print(f"\nEvaluating: {app_dir.name}")
    print("=" * 60)

    # Detect template type
    template = detect_template(app_dir)
    print(f"  Template: {template}")

    # Skip only if template is unknown and has Dockerfile
    if template == "unknown" and (app_dir / "Dockerfile").exists():
        print("  ⚠️  Docker-only apps not yet supported with Docker wrapper")
        metrics = FullMetrics()
        metrics.template_type = "docker"
        return EvalResult(
            app_name=app_dir.name,
            app_dir=str(app_dir),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            metrics=metrics,
            issues=["Docker-only apps not yet supported"],
            details={},
        )

    metrics = FullMetrics()
    metrics.template_type = template
    issues = []
    details = {}

    workspace = None
    try:
        # Create Docker workspace for this app
        print("  [0/7] Creating Docker workspace...")
        workspace = create_ts_workspace_docker(
            app_dir=app_dir,
            template=template,
            port=port,
        )

        # Metric 0: Install dependencies
        print("  [0/7] Installing dependencies...")
        install_result = install_dependencies(workspace)
        deps_installed = install_result.exit_code == 0

        if not deps_installed:
            issues.append("Dependencies installation failed")
            print(f"    ⚠️  Failed: {install_result.stderr[:200]}")
        else:
            print("    ✅ Dependencies installed")

        # Metric 1: Build
        print("  [1/7] Checking build success...")
        build_start = time.time()
        build_result = build_app(workspace)
        build_time = time.time() - build_start

        build_success = build_result.exit_code == 0
        metrics.build_success = build_success
        metrics.build_time_sec = round(build_time, 1)
        metrics.has_dockerfile = (app_dir / "Dockerfile").exists()

        if not build_success:
            issues.append("Build failed")
            print(f"    ⚠️  Build failed: {build_result.stderr[:200]}")
        else:
            print("    ✅ Build successful")

        # Metric 2: Runtime
        print("  [2/7] Checking runtime success...")
        startup_start = time.time()
        try:
            runtime_result = check_runtime(workspace)
            startup_time = time.time() - startup_start

            runtime_success = runtime_result.exit_code == 0
            metrics.runtime_success = runtime_success
            metrics.startup_time_sec = round(startup_time, 1)

            if not runtime_success:
                issues.append("Runtime check failed")
                print(f"    ⚠️  Runtime failed (exit {runtime_result.exit_code})")
                if runtime_result.stderr:
                    print(f"       stderr: {runtime_result.stderr[:500]}")
            else:
                print(f"    ✅ Runtime successful (startup: {startup_time:.1f}s)")
        except Exception as e:
            runtime_success = False
            metrics.runtime_success = False
            metrics.startup_time_sec = 0.0
            issues.append(f"Runtime check error: {str(e)[:100]}")
            print(f"    ⚠️  Runtime check error: {str(e)[:200]}")

        # Metric 3: Type safety (requires dependencies)
        if deps_installed:
            print("  [3/7] Checking type safety...")
            typecheck_result = check_types(workspace)
            type_safety = typecheck_result.exit_code == 0
            metrics.type_safety = type_safety

            if not type_safety:
                print(f"    ⚠️  Type errors: {typecheck_result.stderr[:200]}")
            else:
                print("    ✅ Type safety passed")
        else:
            print("  [3/7] Skipping type safety (dependencies failed)")

        # Metric 4: Tests (requires dependencies)
        if deps_installed:
            print("  [4/7] Checking tests pass...")
            test_port = port + 1000
            try:
                test_result = run_tests(workspace, test_port)
                tests_pass = test_result.exit_code == 0
                metrics.tests_pass = tests_pass

                # Parse coverage from output
                coverage_pct = 0.0
                output = test_result.stdout + test_result.stderr
                for line in output.split("\n"):
                    if "all files" in line.lower() and "%" in line:
                        parts = line.split("|")
                        if len(parts) >= 2:
                            try:
                                coverage_pct = float(parts[1].strip().replace("%", ""))
                            except (ValueError, IndexError):
                                pass

                metrics.test_coverage_pct = coverage_pct

                # Check if test files exist
                test_files = list(app_dir.glob("**/*.test.ts")) + list(app_dir.glob("**/*.spec.ts"))
                test_files = [f for f in test_files if "node_modules" not in str(f)]
                metrics.has_tests = len(test_files) > 0

                if not tests_pass:
                    issues.append("Tests failed")
                    print(f"    ⚠️  Tests failed (exit {test_result.exit_code})")
                else:
                    print(f"    ✅ Tests passed (coverage: {coverage_pct:.1f}%)")
            except Exception as e:
                issues.append(f"Test execution error: {str(e)}")
                print(f"    ⚠️  Test error: {str(e)[:200]}")
        else:
            print("  [4/7] Skipping tests (dependencies failed)")

        # Metrics 5-7: LLM/VLM checks (skip in fast mode)
        if fast_mode:
            print("  [5-7/7] Skipping DB/data/UI checks (--fast mode)")
        elif runtime_success:
            print("  [5/7] Checking Databricks connectivity...")
            db_success = check_databricks_connectivity(app_dir, template, port)
            metrics.databricks_connectivity = db_success
            if not db_success:
                issues.append("Databricks connectivity failed")

            # Metric 6: Data validity (LLM)
            if db_success:
                data_returned, data_details = check_data_validity_llm(app_dir, prompt, template)
                metrics.data_returned = data_returned
                if not data_returned:
                    issues.append(f"Data validity concerns: {data_details}")

            # Metric 7: UI functional (VLM)
            print("  [7/7] Checking UI renders (VLM)...")
            ui_renders, ui_details = check_ui_functional_vlm(app_dir, prompt)
            metrics.ui_renders = ui_renders
            if not ui_renders:
                issues.append(f"UI concerns: {ui_details}")
        else:
            print("  [5-7/7] Skipping DB/data/UI checks (runtime failed)")

    except Exception as e:
        issues.append(f"Evaluation error: {str(e)}")
        print(f"  ⚠️  Exception during evaluation: {e}")
    finally:
        # Always cleanup container
        if workspace:
            workspace.cleanup()

    # Calculate DevX metrics (run even if evaluation failed)
    try:
        print("  [8/9] Checking local runability...")
        local_score, local_details = check_local_runability(app_dir, template)
        metrics.local_runability_score = local_score
        details["local_runability"] = local_details
        if local_score < 3:
            issues.append(
                f"Local runability concerns ({local_score}/5)"
            )

        print("  [9/9] Checking deployability...")
        deploy_score, deploy_details = check_deployability(app_dir)
        metrics.deployability_score = deploy_score
        details["deployability"] = deploy_details
        if deploy_score < 3:
            issues.append(
                f"Deployability concerns ({deploy_score}/5)"
            )
    except Exception as e:
        print(f"  ⚠️  Could not calculate DevX metrics: {e}")

    # Calculate composite score
    try:
        metrics.appeval_100 = calculate_appeval_100(
            build_success=metrics.build_success,
            runtime_success=metrics.runtime_success,
            type_safety=metrics.type_safety,
            tests_pass=metrics.tests_pass,
            databricks_connectivity=metrics.databricks_connectivity,
            data_metric=metrics.data_returned,
            ui_metric=metrics.ui_renders,
            local_runability_score=metrics.local_runability_score,
            deployability_score=metrics.deployability_score,
        )
    except Exception as e:
        print(f"  ⚠️  Could not calculate appeval_100: {e}")

    print(f"\nIssues: {len(issues)}")

    return EvalResult(
        app_name=app_dir.name,
        app_dir=str(app_dir),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        metrics=metrics,
        issues=issues,
        details=details,
    )


def evaluate_app_docker_with_metadata(
    app_dir: Path,
    prompt: str | None,
    gen_metrics: dict,
    index: int,
    total: int,
    port: int = 8000,
    fast_mode: bool = False,
) -> dict | None:
    """Wrapper for evaluate_app_docker that adds generation metrics.

    Args:
        app_dir: Path to the app directory
        prompt: Optional prompt used to generate the app
        gen_metrics: Dict of app_name -> generation metrics
        index: Current app index (1-based)
        total: Total number of apps
        port: Port to use for the app
        fast_mode: Skip slow LLM/VLM checks

    Returns:
        Dict with evaluation result and generation metrics, or None on error
    """
    print(f"\n[{index}/{total}] {app_dir.name}")

    try:
        result = evaluate_app_docker(app_dir, prompt, port, fast_mode=fast_mode)
        result_dict = asdict(result)

        # Add generation metrics if available
        if app_dir.name in gen_metrics:
            result_dict["generation_metrics"] = gen_metrics[app_dir.name]

        return result_dict

    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"❌ Error evaluating {app_dir.name}: {e}")
        return None
