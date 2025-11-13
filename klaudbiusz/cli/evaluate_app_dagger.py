#!/usr/bin/env python3
"""Async Dagger-based evaluation script for generated Databricks apps.

Uses Dagger to run evaluations in isolated containers, eliminating port
conflicts and machine environment pollution.
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Add the cli directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Add agent to Python path for workspace imports
agent_path = Path(__file__).parent.parent.parent / "agent"
if str(agent_path) not in sys.path:
    sys.path.insert(0, str(agent_path))

from dotenv import load_dotenv

# Load environment variables
env_paths = [
    Path(__file__).parent.parent.parent / "edda" / ".env",
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent / ".env",
]
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path, override=True)
        break

import dagger

from ts_workspace import (
    create_ts_workspace,
    install_dependencies,
    build_app,
    check_runtime,
    run_tests,
    check_types,
)

# Import original helper functions and classes
from evaluate_app import (
    FullMetrics,
    EvalResult,
    check_databricks_connectivity,
    check_data_validity_llm,
    check_ui_functional_vlm,
    check_local_runability,
    check_deployability,
    load_prompts_from_bulk_results,
)
from template_detection import detect_template


async def evaluate_app_async(
    client: dagger.Client,
    app_dir: Path,
    prompt: str | None = None,
    port: int = 8000,
) -> EvalResult:
    """Run full evaluation on an app using Dagger.

    Args:
        client: Dagger client connection
        app_dir: Path to the app directory
        prompt: Optional prompt used to generate the app
        port: Port to use for the app (unique per parallel execution)
    """
    print(f"\nEvaluating: {app_dir.name}")
    print("=" * 60)

    # Detect template type
    template = detect_template(app_dir)
    print(f"  Template: {template}")

    # Skip only if template is unknown and has Dockerfile
    if template == "unknown" and (app_dir / "Dockerfile").exists():
        print("  ⚠️  Docker-only apps not yet supported with Dagger wrapper")
        # Return minimal result
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

    try:
        # Create Dagger workspace for this app
        print("  [0/7] Creating Dagger workspace...")
        workspace = await create_ts_workspace(
            client=client,
            app_dir=app_dir,
            template=template,
            port=port,
        )

        # Metric 0: Install dependencies
        print("  [0/7] Installing dependencies...")
        install_result = await install_dependencies(workspace)
        deps_installed = install_result.exit_code == 0

        if not deps_installed:
            issues.append("Dependencies installation failed")
            print(f"    ⚠️  Failed: {install_result.stderr}")
        else:
            print("    ✅ Dependencies installed")

        # Metric 1: Build
        print("  [1/7] Checking build success...")
        build_start = time.time()
        build_result = await build_app(workspace)
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
            runtime_result = await check_runtime(workspace)
            startup_time = time.time() - startup_start

            runtime_success = runtime_result.exit_code == 0
            metrics.runtime_success = runtime_success
            metrics.startup_time_sec = round(startup_time, 1)

            if not runtime_success:
                issues.append("Runtime check failed")
                print(f"    ⚠️  Runtime failed (exit {runtime_result.exit_code})")
                if runtime_result.stdout:
                    print(f"       stdout: {runtime_result.stdout[:300]}")
                if runtime_result.stderr:
                    print(f"       stderr: {runtime_result.stderr[:300]}")
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
            typecheck_result = await check_types(workspace)
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
            # Use unique test port to avoid conflicts
            test_port = port + 1000
            try:
                test_result = await run_tests(workspace, test_port)
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
                backend_dirs = [app_dir / "server", app_dir / "backend"]
                has_tests = False
                for backend_dir in backend_dirs:
                    if backend_dir.exists() and (backend_dir / "src").exists():
                        test_files = list((backend_dir / "src").glob("**/*.test.ts"))
                        if test_files:
                            has_tests = True
                            break
                metrics.has_tests = has_tests

                if not tests_pass:
                    issues.append("Tests failed")
                    print(f"    ⚠️  Tests failed (exit {test_result.exit_code})")
                    print(f"       stderr: {test_result.stderr[:300]}")
                else:
                    print(f"    ✅ Tests passed (coverage: {coverage_pct:.1f}%)")
            except Exception as e:
                issues.append(f"Test execution error: {str(e)}")
                print(f"    ⚠️  Test error: {str(e)[:200]}")
        else:
            print("  [4/7] Skipping tests (dependencies failed)")

        # Remaining checks run on host (not in Dagger)

        # Metric 5: Databricks connectivity (only if runtime succeeded)
        if runtime_success:
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
            ui_renders, ui_details = check_ui_functional_vlm(app_dir, prompt)
            metrics.ui_renders = ui_renders
            if not ui_renders:
                issues.append(f"UI concerns: {ui_details}")
        else:
            print("  [5-7/7] Skipping DB/data/UI checks (runtime failed)")

        # Metric 8: Local runability
        local_score, local_details = check_local_runability(app_dir, template)
        metrics.local_runability_score = local_score
        details["local_runability"] = local_details
        if local_score < 3:
            issues.append(
                f"Local runability concerns ({local_score}/5): {'; '.join([d for d in local_details if '✗' in d])}"
            )

        # Metric 9: Deployability
        deploy_score, deploy_details = check_deployability(app_dir)
        metrics.deployability_score = deploy_score
        details["deployability"] = deploy_details
        if deploy_score < 3:
            issues.append(
                f"Deployability concerns ({deploy_score}/5): {'; '.join([d for d in deploy_details if '✗' in d])}"
            )

        # Calculate composite score
        from eval_metrics import calculate_appeval_100, eff_units

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

        # Calculate efficiency metric
        generation_metrics_file = app_dir / "generation_metrics.json"
        if generation_metrics_file.exists():
            generation_metrics = json.loads(generation_metrics_file.read_text())
            tokens = generation_metrics.get("input_tokens", 0) + generation_metrics.get("output_tokens", 0)
            turns = generation_metrics.get("turns")
            validations = generation_metrics.get("validation_runs")

            metrics.eff_units = eff_units(
                tokens_used=tokens if tokens > 0 else None, agent_turns=turns, validation_runs=validations
            )

        # Add LOC count
        metrics.total_loc = sum(1 for f in app_dir.rglob("*.ts") if f.is_file() and "node_modules" not in str(f))

    except Exception as e:
        issues.append(f"Evaluation error: {str(e)}")
        print(f"  ⚠️  Exception during evaluation: {e}")

    print(f"\nIssues: {len(issues)}")

    return EvalResult(
        app_name=app_dir.name,
        app_dir=str(app_dir),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        metrics=metrics,
        issues=issues,
        details=details,
    )


async def main_async():
    """Async main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python evaluate_app_dagger.py <app_directory>")
        print("   or: python evaluate_app_dagger.py --all")
        sys.exit(1)

    script_dir = Path(__file__).parent
    apps_dir = script_dir.parent / "app"

    # Load prompts
    results_files = sorted(apps_dir.glob("bulk_run_results_*.json"), reverse=True)
    prompts, bulk_metadata = load_prompts_from_bulk_results(results_files[0]) if results_files else ({}, {})

    # Create Dagger client
    async with dagger.Connection() as client:
        if sys.argv[1] == "--all":
            # Evaluate all apps
            results = []
            port = 8000

            for app_dir in sorted(apps_dir.iterdir()):
                if app_dir.is_dir() and not app_dir.name.startswith("."):
                    prompt = prompts.get(app_dir.name)
                    result = await evaluate_app_async(client, app_dir, prompt, port)
                    results.append(asdict(result))
                    port += 1  # Increment port for next app

            # Save results
            output_data = {
                "bulk_run_metadata": bulk_metadata,
                "eval_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "results": results,
            }
            output_file = script_dir / f"eval_results_{int(time.time())}.json"
            output_file.write_text(json.dumps(output_data, indent=2))
            print(f"\n\nResults saved to: {output_file}")

        else:
            # Evaluate single app
            app_dir = Path(sys.argv[1])
            if not app_dir.exists():
                print(f"Error: Directory not found: {app_dir}")
                sys.exit(1)

            prompt = prompts.get(app_dir.name)
            result = await evaluate_app_async(client, app_dir, prompt, port=8000)

            # Print and save result
            print("\n" + "=" * 60)
            print("EVALUATION RESULT")
            print("=" * 60)
            print(json.dumps(asdict(result), indent=2))

            output_file = app_dir / "eval_result.json"
            output_file.write_text(json.dumps(asdict(result), indent=2))
            print(f"\nResult saved to: {output_file}")


def main():
    """Sync wrapper for async main."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
