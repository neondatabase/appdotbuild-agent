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

# Add the cli directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

# Load environment variables from .env file - try multiple locations
env_paths = [
    Path(__file__).parent.parent.parent / "edda" / ".env",
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent / ".env",
]
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path, override=True)  # override=True to ensure vars are set
        break

try:
    import anthropic
except ImportError:
    anthropic = None

from eval_metrics import calculate_appeval_100, eff_units
from eval_checks import check_databricks_connectivity as _check_db_connectivity, extract_sql_queries
from template_detection import detect_template


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

    # Composite score
    appeval_100: float = 0.0

    # Efficiency metric (lower is better) - optional
    eff_units: float | None = None

    # Template information
    template_type: str = "unknown"


@dataclass
class EvalResult:
    """Full evaluation result for an app."""

    app_name: str
    app_dir: str
    timestamp: str
    metrics: FullMetrics
    issues: list[str]
    details: dict[str, Any]


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

    dockerfile = app_dir / "Dockerfile"
    has_dockerfile = dockerfile.exists()

    if not has_dockerfile:
        return False, {"build_time_sec": 0.0, "has_dockerfile": False}

    success, stdout, stderr = run_command(
        ["docker", "build", "-t", f"eval-{app_dir.name}", "."],
        cwd=str(app_dir),
        timeout=300,
    )

    build_time = time.time() - start
    return success, {"build_time_sec": round(build_time, 1), "has_dockerfile": True}


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
    if "DATABRICKS_WAREHOUSE_ID" in os.environ:
        env_vars.extend(["-e", f"DATABRICKS_WAREHOUSE_ID={os.environ['DATABRICKS_WAREHOUSE_ID']}"])

    success, stdout, stderr = run_command(
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
        success, stdout, stderr = run_command(
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

    # Check if root-level package.json exists (monorepo style)
    root_pkg = app_dir / "package.json"
    if root_pkg.exists():
        root_success, _, _ = run_command(
            ["npm", "install"],
            cwd=str(app_dir),
            timeout=180,
        )
        if root_success:
            print("    ✅ Dependencies installed (root)")
            return True
        else:
            print("    ⚠️  Root npm install failed")

    # Try server/ or backend/
    server_dir = app_dir / "server" if (app_dir / "server").exists() else app_dir / "backend"
    if server_dir.exists() and (server_dir / "package.json").exists():
        server_success, _, _ = run_command(
            ["npm", "install"],
            cwd=str(server_dir),
            timeout=180,
        )
        if not server_success:
            print(f"    ⚠️  {server_dir.name} npm install failed")
            return False
    else:
        print(f"    ⚠️  No {server_dir.name} directory or package.json")
        return False

    # Try client/ or frontend/
    client_dir = app_dir / "client" if (app_dir / "client").exists() else app_dir / "frontend"
    if client_dir.exists() and (client_dir / "package.json").exists():
        client_success, _, _ = run_command(
            ["npm", "install"],
            cwd=str(client_dir),
            timeout=180,
        )
        if not client_success:
            print(f"    ⚠️  {client_dir.name} npm install failed")
            return False

    print("    ✅ Dependencies installed")
    return True


def check_type_safety(app_dir: Path) -> bool:
    """Metric 3: TypeScript compiles without errors."""
    print("  [3/7] Checking type safety...")

    # Check server or backend
    server_dir = app_dir / "server" if (app_dir / "server").exists() else app_dir / "backend"
    server_success = True
    if server_dir.exists():
        server_success, _, _ = run_command(
            ["npx", "tsc", "--noEmit"],
            cwd=str(server_dir),
            timeout=60,
        )

    # Check client or frontend
    client_dir = app_dir / "client" if (app_dir / "client").exists() else app_dir / "frontend"
    client_success = True
    if client_dir.exists():
        client_success, _, _ = run_command(
            ["npx", "tsc", "--noEmit"],
            cwd=str(client_dir),
            timeout=60,
        )

    return server_success and client_success


def check_tests_pass(app_dir: Path) -> tuple[bool, float, bool]:
    """Metric 4: Tests pass with coverage."""
    print("  [4/7] Checking tests pass...")

    # Find server or backend dir
    server_dir = app_dir / "server" if (app_dir / "server").exists() else app_dir / "backend"

    if not server_dir.exists():
        return False, 0.0, False

    success, stdout, stderr = run_command(
        ["npm", "test", "--", "--experimental-test-coverage"],
        cwd=str(server_dir),
        timeout=120,
    )

    # Check if tests exist
    src_dir = server_dir / "src"
    test_files = []
    if src_dir.exists():
        test_files = list(src_dir.glob("*.test.ts")) + list(src_dir.glob("**/*.test.ts"))
    has_tests = len(test_files) > 0

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

    return success, coverage_pct, has_tests


def check_databricks_connectivity(app_dir: Path, template: str = "trpc") -> bool:
    """Metric 5: Can connect to Databricks and execute queries."""
    print("  [5/7] Checking Databricks connectivity...")
    return _check_db_connectivity(app_dir, 8000, run_command, template)


def check_data_validity_llm(app_dir: Path, prompt: str | None, template: str = "trpc") -> tuple[bool, str]:
    """Metric 6: Binary check - does app return valid data from Databricks."""
    print("  [6/7] Checking data validity (LLM)...")

    if not anthropic or not prompt:
        return False, "Skipped: Anthropic client not available or no prompt"

    # Extract SQL queries using template-aware extraction
    queries = extract_sql_queries(app_dir, template)

    if not queries:
        return False, "No SQL query found"

    # Use first query for validation
    sql_query = queries[0]

    # Call LLM for validation - simplified to binary check
    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[
                {
                    "role": "user",
                    "content": f"""Analyze this SQL query for a Databricks app.

Prompt: {prompt}

SQL Query:
{sql_query}

Answer YES or NO: Does this query look valid and likely to return meaningful data?
Consider:
- Does the query match the prompt requirements?
- Are the column names meaningful?
- Are there obvious syntax or logic errors?

Respond with ONLY: YES or NO""",
                }
            ],
        )

        # Extract text from first content block
        content_block = message.content[0]
        response_text = getattr(content_block, 'text', '').strip().upper()
        if response_text:
            return "YES" in response_text, response_text
        else:
            return False, "Invalid response format"

    except Exception as e:
        return False, f"LLM check failed: {str(e)}"


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

        # Extract text from first content block
        content_block = message.content[0]
        response_text = getattr(content_block, 'text', '').strip().upper()
        if not response_text:
            return False, "Invalid response format"

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
    server_dir = app_dir / "server" if (app_dir / "server").exists() else app_dir / "backend"
    if server_dir.exists():
        server_install, _, _ = run_command(
            ["npm", "install", "--dry-run"],
            cwd=str(server_dir),
            timeout=60,
        )
        if server_install:
            score += 1
            details.append(f"✓ {server_dir.name} dependencies installable")
        else:
            details.append(f"✗ {server_dir.name} npm install issues")
    else:
        details.append("✗ No server/backend directory")

    # Check 4: npm start command defined
    server_pkg = server_dir / "package.json" if server_dir.exists() else None
    if server_pkg and server_pkg.exists():
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
    entry_point = None
    if server_dir.exists():
        entry_point = server_dir / "src" / "index.ts"
        if not entry_point.exists():
            entry_point = server_dir / "index.ts"

    if entry_point and entry_point.exists():
        score += 1
        details.append(f"✓ Entry point exists ({entry_point.relative_to(app_dir)})")
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
        success, _, _ = run_command(
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

    # Detect template type
    template = detect_template(app_dir)
    print(f"  Template: {template}")

    metrics = FullMetrics()
    metrics.template_type = template
    issues = []
    details = {}
    container_name = f"eval-{app_dir.name}-{int(time.time())}"

    runtime_success = False  # Initialize to avoid UnboundLocalError

    try:
        # Install dependencies first (needed for TypeScript and tests)
        deps_installed = install_dependencies(app_dir)

        # Metric 1: Build
        build_success, build_meta = check_build_success(app_dir)
        metrics.build_success = build_success
        metrics.build_time_sec = build_meta.get("build_time_sec", 0.0)
        metrics.has_dockerfile = build_meta.get("has_dockerfile", False)
        if not build_success:
            issues.append("Docker build failed")

        # Metric 2: Runtime (only if build succeeded)
        if build_success:
            runtime_success, runtime_meta = check_runtime_success(app_dir, container_name)
            metrics.runtime_success = runtime_success
            metrics.startup_time_sec = runtime_meta.get("startup_time_sec", 0.0)
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
            tests_pass, coverage, has_tests = check_tests_pass(app_dir)
            metrics.tests_pass = tests_pass
            metrics.test_coverage_pct = coverage
            metrics.has_tests = has_tests
            if not tests_pass:
                issues.append("Tests failed")
            if coverage < 70:
                issues.append(f"Test coverage below 70% ({coverage:.1f}%)")

        # Metric 5: Databricks connectivity (only if runtime succeeded)
        if runtime_success:
            db_success = check_databricks_connectivity(app_dir, template)
            metrics.databricks_connectivity = db_success
            if not db_success:
                issues.append("Databricks connectivity failed")

            # Metric 6: Data validity (LLM - binary check) - NOT INCLUDED IN SCORE
            if db_success:
                data_returned, data_details = check_data_validity_llm(app_dir, prompt, template)
                metrics.data_returned = data_returned
                if not data_returned:
                    issues.append(f"Data validity concerns: {data_details}")

            # Metric 7: UI functional (VLM - binary check) - NOT INCLUDED IN SCORE
            ui_renders, ui_details = check_ui_functional_vlm(app_dir, prompt)
            metrics.ui_renders = ui_renders
            if not ui_renders:
                issues.append(f"UI concerns: {ui_details}")

        # Metric 8: Local runability (DevX)
        local_score, local_details = check_local_runability(app_dir)
        metrics.local_runability_score = local_score
        details["local_runability"] = local_details
        if local_score < 3:
            issues.append(f"Local runability concerns ({local_score}/5): {'; '.join([d for d in local_details if '✗' in d])}")

        # Metric 9: Deployability (DevX)
        deploy_score, deploy_details = check_deployability(app_dir)
        metrics.deployability_score = deploy_score
        details["deployability"] = deploy_details
        if deploy_score < 3:
            issues.append(f"Deployability concerns ({deploy_score}/5): {'; '.join([d for d in deploy_details if '✗' in d])}")

        # Calculate composite appeval_100 score
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

        # Calculate efficiency metric from generation data if available
        generation_metrics_file = app_dir / "generation_metrics.json"
        if generation_metrics_file.exists():
            generation_metrics = json.loads(generation_metrics_file.read_text())
            tokens = generation_metrics.get("input_tokens", 0) + generation_metrics.get("output_tokens", 0)
            turns = generation_metrics.get("turns")
            validations = generation_metrics.get("validation_runs")

            metrics.eff_units = eff_units(
                tokens_used=tokens if tokens > 0 else None,
                agent_turns=turns,
                validation_runs=validations
            )

        # Add LOC count
        metrics.total_loc = sum(
            1
            for f in app_dir.rglob("*.ts")
            if f.is_file() and "node_modules" not in str(f)
        )

    finally:
        # Always cleanup container if it exists (regardless of success/failure)
        cleanup_container(container_name)

    print(f"\nIssues: {len(issues)}")

    return EvalResult(
        app_name=app_dir.name,
        app_dir=str(app_dir),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        metrics=metrics,
        issues=issues,
        details=details,
    )


def load_prompts_from_bulk_results(bulk_results_file: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """Load app prompts and metadata from bulk_run results JSON.

    Returns:
        Tuple of (prompts_dict, metadata_dict)
    """
    if not bulk_results_file.exists():
        return {}, {}

    try:
        data = json.loads(bulk_results_file.read_text())

        # Handle new format with metadata wrapper
        if "metadata" in data and "results" in data:
            metadata = data["metadata"]
            results = data["results"]
        else:
            # Legacy format without metadata wrapper
            metadata = {}
            results = data

        prompts = {}
        for result in results:
            app_dir = result.get("app_dir")
            prompt = result.get("prompt")
            if app_dir and prompt:
                app_name = Path(app_dir).name
                prompts[app_name] = prompt
        return prompts, metadata
    except Exception:
        return {}, {}


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python evaluate_app.py <app_directory>")
        print("   or: python evaluate_app.py --all")
        sys.exit(1)

    script_dir = Path(__file__).parent
    apps_dir = script_dir.parent / "app"

    # Load prompts and metadata from latest bulk results
    results_files = sorted(apps_dir.glob("bulk_run_results_*.json"), reverse=True)
    prompts, bulk_metadata = load_prompts_from_bulk_results(results_files[0]) if results_files else ({}, {})

    if sys.argv[1] == "--all":
        # Evaluate all apps
        results = []
        for app_dir in sorted(apps_dir.iterdir()):
            if app_dir.is_dir() and not app_dir.name.startswith("."):
                prompt = prompts.get(app_dir.name)
                result = evaluate_app(app_dir, prompt)
                results.append(asdict(result))

        # Save combined results with bulk run metadata
        output_data = {
            "bulk_run_metadata": bulk_metadata,
            "eval_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "results": results,
        }
        output_file = script_dir / f"eval_results_{int(time.time())}.json"
        output_file.write_text(json.dumps(output_data, indent=2))
        print(f"\n\nResults saved to: {output_file}")
        if bulk_metadata:
            print("Bulk run metadata:")
            for key, value in bulk_metadata.items():
                print(f"  {key}: {value}")

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
