#!/usr/bin/env python3
"""Simple evaluation script for generated Databricks apps.

Runs 7 core metrics checks:
1. Build success (Docker)
2. Runtime success (Container + healthcheck)
3. Type safety (TypeScript)
4. Tests pass (npm test)
5. Databricks connectivity (API call)
6. Data validity (LLM-assisted)
7. UI functional (VLM-assisted)

Usage:
    python evaluate_app.py <app_directory>
    python evaluate_app.py --all  # Evaluate all apps in ../app/
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# load environment variables from .env file
load_dotenv()

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Try loading from various locations
    env_paths = [
        Path(__file__).parent.parent.parent / "dabgent" / ".env",
        Path(__file__).parent.parent / ".env",
        Path(__file__).parent / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"Loaded environment from: {env_path}")
            break
except ImportError:
    print("Warning: python-dotenv not installed, relying on system environment variables")

try:
    import anthropic  # type: ignore[import-untyped]
except ImportError:
    anthropic = None  # type: ignore[assignment]


@dataclass
class EvalMetrics:
    """Core evaluation metrics."""

    build_success: bool = False
    runtime_success: bool = False
    type_safety: bool = False
    tests_pass: bool = False
    test_coverage_pct: float = 0.0
    databricks_connectivity: bool = False
    data_validity_score: int = 0
    ui_functional_score: int = 0
    local_runability_score: int = 0
    deployability_score: int = 0


@dataclass
class EvalResult:
    """Full evaluation result for an app."""

    app_name: str
    app_dir: str
    timestamp: str
    metrics: EvalMetrics
    overall_status: str
    issues: list[str]
    metadata: dict[str, Any]


def run_command(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> tuple[bool, str, str]:
    """Run a shell command and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def check_build_success(app_dir: Path) -> tuple[bool, dict]:
    """Metric 1: Docker build succeeds."""
    print("  [1/7] Checking build success...")
    start = time.time()

    success, stdout, stderr = run_command(
        ["docker", "build", "-t", f"eval-{app_dir.name}", "."],
        cwd=str(app_dir),
        timeout=300,
    )

    build_time = time.time() - start
    return success, {"build_time_sec": round(build_time, 1)}


def check_runtime_success(app_dir: Path, container_name: str) -> tuple[bool, dict]:
    """Metric 2: Container starts and health check responds."""
    print("  [2/7] Checking runtime success...")

    # Start container
    env_file = app_dir.parent.parent / ".env"
    env_args = ["--env-file", str(env_file)] if env_file.exists() else []

    # Add Databricks env vars from environment
    env_vars = []
    if "DATABRICKS_HOST" in os.environ:
        env_vars.extend(["-e", f"DATABRICKS_HOST={os.environ['DATABRICKS_HOST']}"])
    if "DATABRICKS_TOKEN" in os.environ:
        env_vars.extend(["-e", f"DATABRICKS_TOKEN={os.environ['DATABRICKS_TOKEN']}"])

    success, _, _ = run_command(
        [
            "docker",
            "run",
            "-d",
            "-p",
            "8000:8000",
            "--name",
            container_name,
            *env_args,
            *env_vars,
            f"eval-{app_dir.name}",
        ],
        timeout=30,
    )

    if not success:
        return False, {}

    # Wait for startup
    time.sleep(5)

    # Check health endpoint
    start = time.time()
    for _ in range(6):  # Try for 30 seconds
        success, stdout, _ = run_command(
            ["curl", "-f", "-s", "http://localhost:8000/healthcheck"],
            timeout=10,
        )
        if success:
            startup_time = time.time() - start
            return True, {"startup_time_sec": round(startup_time, 1)}
        time.sleep(5)

    return False, {}


def install_dependencies(app_dir: Path) -> bool:
    """Install npm dependencies for both client and server."""
    print("  [0/7] Installing dependencies...")

    # Install server dependencies
    server_success, _, _ = run_command(
        ["npm", "install"],
        cwd=str(app_dir / "server"),
        timeout=180,
    )

    if not server_success:
        print("    ⚠️  Server npm install failed")
        return False

    # Install client dependencies
    client_success, _, _ = run_command(
        ["npm", "install"],
        cwd=str(app_dir / "client"),
        timeout=180,
    )

    if not client_success:
        print("    ⚠️  Client npm install failed")
        return False

    print("    ✅ Dependencies installed")
    return True


def check_type_safety(app_dir: Path) -> bool:
    """Metric 3: TypeScript compiles without errors."""
    print("  [3/7] Checking type safety...")

    # Check server
    server_success, _, _ = run_command(
        ["npx", "tsc", "--noEmit"],
        cwd=str(app_dir / "server"),
        timeout=60,
    )

    # Check client
    client_success, _, _ = run_command(
        ["npx", "tsc", "--noEmit"],
        cwd=str(app_dir / "client"),
        timeout=60,
    )

    return server_success and client_success


def check_tests_pass(app_dir: Path) -> tuple[bool, float]:
    """Metric 4: Tests pass with coverage."""
    print("  [4/7] Checking tests pass...")

    success, stdout, stderr = run_command(
        ["npm", "test", "--", "--experimental-test-coverage"],
        cwd=str(app_dir / "server"),
        timeout=120,
    )

    # Parse coverage from output (node's test runner output format)
    coverage_pct = 0.0
    output = stdout + stderr
    for line in output.split("\n"):
        if "all files" in line.lower() and "%" in line:
            # Try to extract percentage
            parts = line.split("|")
            if len(parts) >= 2:
                try:
                    coverage_pct = float(parts[1].strip().replace("%", ""))
                except (ValueError, IndexError):
                    pass

    return success, coverage_pct


def check_databricks_connectivity(app_dir: Path) -> bool:
    """Metric 5: Can connect to Databricks and execute queries."""
    print("  [5/7] Checking Databricks connectivity...")

    # Try to call the first tRPC endpoint
    # First, discover available procedures by inspecting the router
    index_ts = app_dir / "server" / "src" / "index.ts"
    if not index_ts.exists():
        return False

    # Look for procedure names in the file
    content = index_ts.read_text()
    procedures = []
    for line in content.split("\n"):
        if "publicProcedure" in line and ":" in line:
            # Extract procedure name (simple heuristic)
            parts = line.split(":")
            if parts:
                proc_name = parts[0].strip()
                if proc_name and proc_name != "healthcheck":
                    procedures.append(proc_name)

    # Try first data procedure (skip healthcheck)
    for proc in procedures[:3]:  # Try up to 3 endpoints
        success, stdout, _ = run_command(
            [
                "curl",
                "-f",
                "-s",
                "-X",
                "POST",
                f"http://localhost:8000/api/{proc}",
                "-H",
                "Content-Type: application/json",
                "-d",
                "{}",
            ],
            timeout=60,
        )

        if success:
            try:
                result = json.loads(stdout)
                # Check if we got data back
                if result and "result" in result:
                    return True
            except json.JSONDecodeError:
                pass

    return False


def check_data_validity_llm(app_dir: Path, prompt: str | None) -> tuple[int, str]:
    """Metric 6: LLM validates SQL logic and results."""
    print("  [6/7] Checking data validity (LLM)...")

    if not anthropic or not prompt:
        return 0, "Skipped: Anthropic client not available or no prompt"

    # Extract SQL queries from source
    index_ts = app_dir / "server" / "src" / "index.ts"
    if not index_ts.exists():
        return 0, "No index.ts found"

    content = index_ts.read_text()

    # Extract first SQL query
    sql_query = ""
    in_query = False
    for line in content.split("\n"):
        if "query = `" in line:
            in_query = True
        if in_query:
            sql_query += line + "\n"
            if "`;" in line:
                break

    if not sql_query:
        return 0, "No SQL query found"

    # Call LLM for validation
    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": f"""Analyze this SQL query for a Databricks app.

Prompt: {prompt}

SQL Query:
{sql_query}

Rate the query on these criteria (answer yes/no for each):
1. Does the query match the prompt requirements?
2. Are the column names meaningful?
3. Do the aggregations make sense?
4. Are there any obvious logic errors?
5. Does the query look correct?

Respond in this exact format:
SCORE: X/5
ISSUES: [list issues or "None"]""",
                }
            ],
        )

        response_text = message.content[0].text  # type: ignore[union-attr]
        score = 0
        issues = "Unknown"

        for line in response_text.split("\n"):
            if "SCORE:" in line:
                try:
                    score = int(line.split("/")[0].split(":")[-1].strip())
                except ValueError:
                    pass
            if "ISSUES:" in line:
                issues = line.split(":", 1)[1].strip()

        return score, issues

    except Exception as e:
        return 0, f"LLM check failed: {str(e)}"


def check_ui_functional_vlm(app_dir: Path, prompt: str | None) -> tuple[bool, str]:
    """Metric 7: VLM binary check - does UI render without errors?

    Returns: (passes: bool, details: str)
    """
    print("  [7/7] Checking UI renders (VLM)...")

    if not anthropic:
        return False, "Skipped: Anthropic client not available"

    # Find screenshot
    screenshot_dir = app_dir / "screenshot_output"
    screenshot_path = screenshot_dir / "screenshot.png"

    if not screenshot_path.exists():
        # Try old location
        screenshot_path = app_dir / "screenshot.png"

    if not screenshot_path.exists():
        return False, "No screenshot found"

    # Read screenshot as base64
    import base64

    image_data = base64.standard_b64encode(screenshot_path.read_bytes()).decode("utf-8")

    # Call VLM for validation
    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        },
                        {
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
                        },
                    ],
                }
            ],
        )

        response_text = message.content[0].text  # type: ignore[union-attr].strip().upper()

        # Binary check: PASS or FAIL
        if "PASS" in response_text:
            return True, "UI renders without errors"
        else:
            return False, f"VLM check failed: {response_text}"

    except Exception as e:
        return False, f"VLM check failed: {str(e)}"


def check_local_runability(app_dir: Path) -> tuple[int, list[str]]:
    """Metric 8: Local runability - how easy is it to run locally?"""
    print("  [8/9] Checking local runability...")

    score = 0
    details = []

    # Check 1: README exists with setup instructions
    readme = app_dir / "README.md"
    if readme.exists():
        content = readme.read_text().lower()
        if any(word in content for word in ["setup", "installation", "getting started", "quick start"]):
            score += 1
            details.append("✓ README with setup instructions")
        else:
            details.append("✗ README exists but no setup instructions")
    else:
        details.append("✗ No README.md")

    # Check 2: .env.example or .env.template exists
    if (app_dir / ".env.example").exists() or (app_dir / ".env.template").exists():
        score += 1
        details.append("✓ Environment template exists")
    else:
        details.append("✗ No .env.example or .env.template")

    # Check 3: Dependencies install cleanly
    server_install, _, _ = run_command(
        ["npm", "install", "--dry-run"],
        cwd=str(app_dir / "server"),
        timeout=60,
    )
    if server_install:
        score += 1
        details.append("✓ Server dependencies installable")
    else:
        details.append("✗ Server npm install issues")

    # Check 4: npm start command defined
    server_pkg = app_dir / "server" / "package.json"
    if server_pkg.exists():
        try:
            pkg_data = json.loads(server_pkg.read_text())
            if "start" in pkg_data.get("scripts", {}):
                score += 1
                details.append("✓ npm start command defined")
            else:
                details.append("✗ No npm start command")
        except json.JSONDecodeError:
            details.append("✗ Invalid package.json")
    else:
        details.append("✗ No package.json found")

    # Check 5: Test if app can start locally (lightweight check - just see if it's runnable)
    # We won't actually start it here as it's redundant with runtime check
    # Instead, check if entry point exists
    entry_point = app_dir / "server" / "src" / "index.ts"
    if entry_point.exists():
        score += 1
        details.append("✓ Entry point exists (server/src/index.ts)")
    else:
        details.append("✗ No entry point found")

    return score, details


def check_deployability(app_dir: Path) -> tuple[int, list[str]]:
    """Metric 9: Deployability - how production-ready is this?"""
    print("  [9/9] Checking deployability...")

    score = 0
    details = []

    # Check 1: Dockerfile exists (already checked in build_success, but recheck)
    dockerfile = app_dir / "Dockerfile"
    if dockerfile.exists():
        score += 1
        details.append("✓ Dockerfile exists")
    else:
        details.append("✗ No Dockerfile")
        return score, details  # Can't check other items without Dockerfile

    # Check 2: Multi-stage build or optimized image
    dockerfile_content = dockerfile.read_text()
    is_multistage = "FROM" in dockerfile_content and dockerfile_content.count("FROM") > 1
    is_alpine = "alpine" in dockerfile_content.lower()

    if is_multistage:
        score += 1
        details.append("✓ Multi-stage build for optimization")
    elif is_alpine:
        score += 1
        details.append("✓ Alpine-based image for smaller size")
    else:
        details.append("✗ No multi-stage build or alpine optimization")

    # Check 3: Health check defined in Dockerfile
    if "HEALTHCHECK" in dockerfile_content:
        score += 1
        details.append("✓ HEALTHCHECK defined in Dockerfile")
    else:
        details.append("✗ No HEALTHCHECK in Dockerfile")

    # Check 4: No hardcoded secrets
    has_secrets = False
    for pattern in ["DATABRICKS_TOKEN=dapi", "password=", "api_key=", "secret="]:
        success, stdout, _ = run_command(
            ["grep", "-r", "-i", pattern, ".", "--exclude-dir=node_modules", "--exclude-dir=.git"],
            cwd=str(app_dir),
            timeout=10,
        )
        if success:  # grep returns 0 if pattern found
            has_secrets = True
            break

    if not has_secrets:
        score += 1
        details.append("✓ No hardcoded secrets detected")
    else:
        details.append("✗ Potential hardcoded secrets found")

    # Check 5: Deployment config exists
    deploy_files = ["docker-compose.yml", "kubernetes.yaml", "k8s.yaml", "fly.toml", "render.yaml"]
    has_deploy_config = any((app_dir / f).exists() for f in deploy_files)

    if has_deploy_config:
        score += 1
        details.append("✓ Deployment config found")
    else:
        # Build script is acceptable alternative
        build_script = app_dir / "build.sh"
        if build_script.exists():
            score += 1
            details.append("✓ Build script exists")
        else:
            details.append("✗ No deployment config or build script")

    return score, details


def cleanup_container(container_name: str):
    """Stop and remove container."""
    run_command(["docker", "stop", container_name], timeout=10)
    run_command(["docker", "rm", container_name], timeout=10)


def evaluate_app(app_dir: Path, prompt: str | None = None) -> EvalResult:
    """Run full evaluation on an app."""
    print(f"\nEvaluating: {app_dir.name}")
    print("=" * 60)

    metrics = EvalMetrics()
    issues = []
    metadata = {}
    container_name = f"eval-{app_dir.name}-{int(time.time())}"

    runtime_success = False  # Initialize to avoid UnboundLocalError

    try:
        # Install dependencies first (needed for TypeScript and tests)
        deps_installed = install_dependencies(app_dir)

        # Metric 1: Build
        build_success, build_meta = check_build_success(app_dir)
        metrics.build_success = build_success
        metadata.update(build_meta)
        if not build_success:
            issues.append("Docker build failed")

        # Metric 2: Runtime (only if build succeeded)
        if build_success:
            runtime_success, runtime_meta = check_runtime_success(app_dir, container_name)
            metrics.runtime_success = runtime_success
            metadata.update(runtime_meta)
            if not runtime_success:
                issues.append("Container failed to start or healthcheck failed")

        # Metric 3: Type safety (requires dependencies)
        if deps_installed:
            type_safety = check_type_safety(app_dir)
            metrics.type_safety = type_safety
            # Only flag TS errors as issues if they cause build/runtime problems
            # (Since apps use tsx which skips type checking, TS strictness is informational)
            if not type_safety and not build_success:
                issues.append("TypeScript compilation errors prevent build")
        else:
            issues.append("Dependencies installation failed")

        # Metric 4: Tests (requires dependencies)
        if deps_installed:
            tests_pass, coverage = check_tests_pass(app_dir)
            metrics.tests_pass = tests_pass
            metrics.test_coverage_pct = coverage
            if not tests_pass:
                issues.append("Tests failed")
            if coverage < 70:
                issues.append(f"Test coverage below 70% ({coverage:.1f}%)")

        # Metric 5: Databricks connectivity (only if runtime succeeded)
        if runtime_success:
            db_success = check_databricks_connectivity(app_dir)
            metrics.databricks_connectivity = db_success
            if not db_success:
                issues.append("Databricks connectivity failed")

            # Metric 6: Data validity (LLM)
            if db_success:
                data_score, data_issues = check_data_validity_llm(app_dir, prompt)
                metrics.data_validity_score = data_score
                if data_score < 4:
                    issues.append(f"Data validity concerns: {data_issues}")

            # Metric 7: UI functional (VLM)
            ui_score, ui_issues = check_ui_functional_vlm(app_dir, prompt)
            metrics.ui_functional_score = ui_score
            if ui_score < 4:
                issues.append(f"UI concerns: {ui_issues}")

        # Metric 8: Local runability (DevX)
        local_score, local_details = check_local_runability(app_dir)
        metrics.local_runability_score = local_score
        if local_score < 3:
            issues.append(f"Local runability concerns ({local_score}/5): {'; '.join([d for d in local_details if '✗' in d])}")

        # Metric 9: Deployability (DevX)
        deploy_score, deploy_details = check_deployability(app_dir)
        metrics.deployability_score = deploy_score
        if deploy_score < 3:
            issues.append(f"Deployability concerns ({deploy_score}/5): {'; '.join([d for d in deploy_details if '✗' in d])}")

        # Calculate overall status
        critical_checks = [
            metrics.build_success,
            metrics.runtime_success,
            metrics.databricks_connectivity,
        ]
        overall_status = "PASS" if all(critical_checks) else "FAIL"

        # Add metadata
        metadata["total_loc"] = sum(
            1
            for f in app_dir.rglob("*.ts")
            if f.is_file() and "node_modules" not in str(f)
        )

    finally:
        # Always cleanup
        if metrics.runtime_success:
            cleanup_container(container_name)

    print(f"\nStatus: {overall_status}")
    print(f"Issues: {len(issues)}")

    return EvalResult(
        app_name=app_dir.name,
        app_dir=str(app_dir),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        metrics=metrics,
        overall_status=overall_status,
        issues=issues,
        metadata=metadata,
    )


def load_prompts_from_bulk_results(bulk_results_file: Path) -> dict[str, str]:
    """Load app prompts from bulk_run results JSON."""
    if not bulk_results_file.exists():
        return {}

    try:
        data = json.loads(bulk_results_file.read_text())
        prompts = {}
        for result in data:
            app_dir = result.get("app_dir")
            prompt = result.get("prompt")
            if app_dir and prompt:
                app_name = Path(app_dir).name
                prompts[app_name] = prompt
        return prompts
    except Exception:
        return {}


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python evaluate_app.py <app_directory>")
        print("   or: python evaluate_app.py --all")
        sys.exit(1)

    script_dir = Path(__file__).parent
    apps_dir = script_dir.parent / "app"

    # Load prompts from latest bulk results
    results_files = sorted(script_dir.glob("../bulk_run_results_*.json"), reverse=True)
    prompts = load_prompts_from_bulk_results(results_files[0]) if results_files else {}

    if sys.argv[1] == "--all":
        # Evaluate all apps
        results = []
        for app_dir in sorted(apps_dir.iterdir()):
            if app_dir.is_dir() and not app_dir.name.startswith("."):
                prompt = prompts.get(app_dir.name)
                result = evaluate_app(app_dir, prompt)
                results.append(asdict(result))

        # Save combined results
        output_file = script_dir / f"eval_results_{int(time.time())}.json"
        output_file.write_text(json.dumps(results, indent=2))
        print(f"\n\nResults saved to: {output_file}")

    else:
        # Evaluate single app
        app_dir = Path(sys.argv[1])
        if not app_dir.exists():
            print(f"Error: Directory not found: {app_dir}")
            sys.exit(1)

        prompt = prompts.get(app_dir.name)
        result = evaluate_app(app_dir, prompt)

        # Print and save result
        print("\n" + "=" * 60)
        print("EVALUATION RESULT")
        print("=" * 60)
        print(json.dumps(asdict(result), indent=2))

        output_file = app_dir / "eval_result.json"
        output_file.write_text(json.dumps(asdict(result), indent=2))
        print(f"\nResult saved to: {output_file}")


if __name__ == "__main__":
    main()
