#!/usr/bin/env python3
"""
Evaluate all apps in the app/ directory using extended metrics framework.

Includes both direct execution metrics and optional agent-based complementary metrics.
"""
import os
import json
import subprocess
import sys
import time
import base64
import asyncio
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional
import anthropic

# Ensure Claude CLI is in PATH for agent SDK
# This is critical for the Agent SDK to find the Claude Code CLI
if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"/opt/homebrew/bin:{os.environ.get('PATH', '')}"

# Add cli directory to path
sys.path.insert(0, str(Path(__file__).parent / "cli"))

# Import agent SDK
try:
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        ResultMessage,
        AssistantMessage,
        TextBlock,
    )
    AGENT_SDK_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  Claude Agent SDK not available: {e}")
    AGENT_SDK_AVAILABLE = False

APP_DIR = Path("app")
RESULTS = []

# Initialize Anthropic client for VLM evaluations only
ANTHROPIC_CLIENT = None
try:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=api_key)
except Exception as e:
    print(f"⚠️  Could not initialize Anthropic client: {e}")
    ANTHROPIC_CLIENT = None


async def _run_agent_task(prompt: str, task_name: str, app_path: Path) -> tuple[bool, str]:
    """
    Helper function to run an agent task using Claude Agent SDK.

    Args:
        prompt: The task prompt for the agent
        task_name: Name of the task for logging
        app_path: Path to the app directory (for working directory context)

    Returns:
        (success: bool, message: str)
    """
    if not AGENT_SDK_AVAILABLE:
        return None, "Agent SDK not available"

    try:
        # Configure agent options
        options = ClaudeAgentOptions(
            model="claude-sonnet-4-5-20250929",  # Latest Claude 4.5 Sonnet
            max_turns=15,  # Limit turns for evaluation tasks
            permission_mode="bypassPermissions",  # Allow agent to execute commands
            cwd=str(app_path.resolve())  # Set working directory to the app path
        )

        final_message = ""
        tool_uses_count = 0
        error_occurred = False

        # Run agent query with timeout (5 minutes per task)
        async def _execute_query():
            nonlocal final_message, tool_uses_count, error_occurred

            async for message in query(prompt=prompt, options=options):
                match message:
                    case ResultMessage() as result:
                        # Agent completed - check for errors
                        if hasattr(result, 'error') and result.error:
                            error_occurred = True
                            final_message += f"Error: {result.error}\n"

                    case AssistantMessage() as msg:
                        # Collect assistant messages
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                final_message += block.text
                            # Count tool uses as indicators of actual work
                            if hasattr(block, 'type') and 'tool_use' in str(block.type):
                                tool_uses_count += 1

        # Execute with 5-minute timeout
        try:
            await asyncio.wait_for(_execute_query(), timeout=300)  # 5 minutes
        except asyncio.TimeoutError:
            return False, f"Agent task '{task_name}' timed out after 5 minutes"

        # Determine success based on:
        # 1. No errors occurred
        # 2. Agent used tools (indicating it actually tried to do the task)
        # 3. Response doesn't contain clear failure indicators
        if error_occurred:
            return False, f"Agent encountered errors: {final_message[:300]}"

        # Check for failure indicators in the response
        final_lower = final_message.lower()
        failure_indicators = ['failed', 'error', 'cannot', 'unable', 'missing', 'not found']
        success_indicators = ['success', 'passed', 'completed', 'working', 'running']

        has_failure = any(indicator in final_lower for indicator in failure_indicators)
        has_success = any(indicator in final_lower for indicator in success_indicators)

        # If agent used tools and didn't report clear failure, consider it success
        if tool_uses_count > 0 and not has_failure:
            return True, f"Agent completed task (used {tool_uses_count} tools): {final_message[:300]}"
        elif has_success and not has_failure:
            return True, final_message[:300]
        else:
            return False, final_message[:300]

    except Exception as e:
        return False, f"Agent SDK error: {str(e)[:200]}"


def run_command(cmd: str, cwd: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run a command and return exit code, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def check_file_exists(app_path: Path, filename: str) -> bool:
    """Check if a file exists in the app directory."""
    return (app_path / filename).exists()


def evaluate_build_success(app_path: Path, app_name: str) -> tuple[bool, str]:
    """Metric 1: BUILD SUCCESS (Binary)"""
    # Check for different build systems
    if check_file_exists(app_path, "package.json"):
        # Node.js project
        code, stdout, stderr = run_command("npm install", str(app_path), timeout=120)
        if code != 0:
            return False, f"npm install failed: {stderr[:200]}"

        # Check if there's a build script
        try:
            with open(app_path / "package.json") as f:
                pkg = json.load(f)
                if "scripts" in pkg and "build" in pkg["scripts"]:
                    code, stdout, stderr = run_command("npm run build", str(app_path), timeout=120)
                    if code != 0:
                        return False, f"npm run build failed: {stderr[:200]}"
        except:
            pass
        return True, "Build successful (Node.js)"

    elif check_file_exists(app_path, "requirements.txt"):
        # Python project
        code, stdout, stderr = run_command("pip install -r requirements.txt", str(app_path), timeout=120)
        if code != 0:
            return False, f"pip install failed: {stderr[:200]}"
        return True, "Build successful (Python)"

    elif check_file_exists(app_path, "Dockerfile"):
        # Try Docker build
        code, stdout, stderr = run_command(f"docker build -t {app_name} .", str(app_path), timeout=300)
        if code != 0:
            return False, f"Docker build failed: {stderr[:200]}"
        return True, "Build successful (Docker)"

    return False, "No build system detected"


def evaluate_runtime_success(app_path: Path, app_name: str) -> tuple[bool, str]:
    """Metric 2: RUNTIME SUCCESS (Binary)"""
    # Check for different runtime systems
    if check_file_exists(app_path, "package.json"):
        try:
            with open(app_path / "package.json") as f:
                pkg = json.load(f)
                if "scripts" in pkg and "start" in pkg["scripts"]:
                    # Start and check for 5 seconds
                    proc = subprocess.Popen(
                        "npm start",
                        shell=True,
                        cwd=str(app_path),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    time.sleep(5)

                    if proc.poll() is None:
                        # Still running
                        proc.terminate()
                        proc.wait(timeout=5)
                        return True, "App started successfully (Node.js)"
                    else:
                        _, stderr = proc.communicate()
                        return False, f"App crashed immediately: {stderr.decode()[:200]}"
        except Exception as e:
            return False, f"Failed to start: {str(e)}"

    elif check_file_exists(app_path, "app.py") or check_file_exists(app_path, "main.py"):
        # Python Streamlit app
        app_file = "app.py" if check_file_exists(app_path, "app.py") else "main.py"
        proc = subprocess.Popen(
            f"streamlit run {app_file} --server.headless true",
            shell=True,
            cwd=str(app_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        time.sleep(5)

        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
            return True, "App started successfully (Streamlit)"
        else:
            _, stderr = proc.communicate()
            return False, f"App crashed immediately: {stderr.decode()[:200]}"

    return False, "No run method detected"


def evaluate_type_safety(app_path: Path) -> tuple[Optional[bool], str]:
    """Metric 3: TYPE SAFETY (Binary)"""
    if check_file_exists(app_path, "tsconfig.json"):
        code, stdout, stderr = run_command("npx tsc --noEmit", str(app_path), timeout=60)
        if code == 0:
            return True, "TypeScript type check passed"
        else:
            return False, f"TypeScript errors: {stderr[:200]}"

    # Check for Python type checking
    if check_file_exists(app_path, "requirements.txt"):
        # Check if mypy is available
        code, _, _ = run_command("mypy --version", str(app_path))
        if code == 0:
            code, stdout, stderr = run_command("mypy .", str(app_path), timeout=60)
            if code == 0:
                return True, "mypy type check passed"
            else:
                return False, f"mypy errors: {stderr[:200]}"

    return None, "No type checking configured"


def evaluate_tests_pass(app_path: Path) -> tuple[Optional[bool], Optional[float], str]:
    """Metric 4: TESTS PASS (Binary + Coverage %)"""
    if check_file_exists(app_path, "package.json"):
        try:
            with open(app_path / "package.json") as f:
                pkg = json.load(f)
                if "scripts" in pkg and "test" in pkg["scripts"]:
                    code, stdout, stderr = run_command("npm test", str(app_path), timeout=120)
                    if code == 0:
                        # Try to extract coverage if present
                        return True, None, "Tests passed (Node.js)"
                    else:
                        return False, None, f"Tests failed: {stderr[:200]}"
        except:
            pass

    # Check for Python tests
    if check_file_exists(app_path, "test_") or (app_path / "tests").exists():
        code, stdout, stderr = run_command("pytest", str(app_path), timeout=120)
        if code == 0:
            return True, None, "Tests passed (pytest)"
        else:
            return False, None, f"Tests failed: {stderr[:200]}"

    return None, None, "No tests configured"


def evaluate_databricks_connectivity(app_path: Path) -> tuple[bool, str]:
    """Metric 5: DATABRICKS CONNECTIVITY (Binary)"""
    # Check for Databricks imports/usage
    for py_file in app_path.glob("**/*.py"):
        try:
            with open(py_file) as f:
                content = f.read()
                if "databricks" in content.lower() or "databricks-sql-connector" in content:
                    # Check if environment variables are used
                    if "DATABRICKS_HOST" in content or "DATABRICKS_TOKEN" in content:
                        return True, "Databricks connectivity detected with env vars"
                    else:
                        return False, "Databricks used but missing env var configuration"
        except:
            continue

    for ts_file in app_path.glob("**/*.ts"):
        try:
            with open(ts_file) as f:
                content = f.read()
                if "databricks" in content.lower():
                    if "DATABRICKS_HOST" in content or "DATABRICKS_TOKEN" in content:
                        return True, "Databricks connectivity detected with env vars"
                    else:
                        return False, "Databricks used but missing env var configuration"
        except:
            continue

    return False, "No Databricks connectivity detected"


def evaluate_ui_renders(app_path: Path, app_name: str) -> tuple[Optional[bool], str]:
    """Metric 7: UI RENDERS (VLM-based Binary)"""
    if not ANTHROPIC_CLIENT:
        return None, "Anthropic client not available"

    # Look for screenshot file
    screenshot_paths = list(app_path.glob("**/screenshot*.png")) + list(app_path.glob("**/screenshot*.jpg"))

    if not screenshot_paths:
        return None, "No screenshot found"

    screenshot_path = screenshot_paths[0]

    try:
        # Read and encode screenshot
        with open(screenshot_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        # Determine media type
        media_type = "image/png" if screenshot_path.suffix == ".png" else "image/jpeg"

        # Ask Claude to evaluate the UI
        response = ANTHROPIC_CLIENT.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": """Analyze this application screenshot. Does it show a properly rendered UI?

Answer with JSON:
{
    "renders": true/false,
    "reason": "brief explanation"
}

Consider:
- UI elements are visible and not blank
- Layout appears intentional
- No obvious errors or crashes
- Contains actual content/data/visualizations"""
                    }
                ],
            }]
        )

        # Parse response
        response_text = response.content[0].text
        result = json.loads(response_text)

        return result["renders"], result["reason"]

    except Exception as e:
        return None, f"VLM evaluation failed: {str(e)[:100]}"


def invoke_agent_to_build(app_path: Path, app_name: str) -> tuple[Optional[bool], str]:
    """Agent Metric: Actually invoke agent to build this app (Binary)"""
    prompt = f"""You are evaluating the buildability of the application "{app_name}".

Your task:
1. Read package.json or other build configuration files to understand the build system
2. Install dependencies if needed (npm install, pip install, etc.)
3. Execute the build command (npm run build, etc.)
4. Report whether the build succeeded or failed

Working directory: {app_path}

Important:
- Actually execute the build commands using available tools
- Do not modify source code
- Report clear success or failure based on build command exit codes

Please proceed with building the application and report the result."""

    return asyncio.run(_run_agent_task(prompt, "build", app_path))


def invoke_agent_to_run(app_path: Path, app_name: str) -> tuple[Optional[bool], str]:
    """Agent Metric: Actually invoke agent to run this app (Binary)"""
    prompt = f"""You are evaluating the runnability of the application "{app_name}".

Your task:
1. Read package.json or other configuration to find the start/run command
2. Start the application (npm start, streamlit run, etc.)
3. Wait 5-10 seconds to check if it runs without immediate crashes
4. Verify the process is still running
5. Stop the application cleanly

Working directory: {app_path}

Important:
- Actually execute the run commands using available tools
- Use background processes if needed
- Check process status after waiting
- Clean up processes before finishing

Please proceed with running the application and report whether it starts successfully."""

    return asyncio.run(_run_agent_task(prompt, "run", app_path))


def invoke_agent_to_test(app_path: Path, app_name: str) -> tuple[Optional[bool], str]:
    """Agent Metric: Actually invoke agent to run tests (Binary)"""
    prompt = f"""You are evaluating the testability of the application "{app_name}".

Your task:
1. Read package.json or other configuration to find the test command
2. Execute the test command (npm test, pytest, etc.)
3. Check the exit code to determine if tests passed or failed
4. Report the test results

Working directory: {app_path}

Important:
- Actually execute the test commands using available tools
- Report success only if all tests pass (exit code 0)
- Report failure if tests fail or test command doesn't exist

Please proceed with running the tests and report the results."""

    return asyncio.run(_run_agent_task(prompt, "test", app_path))


def invoke_agent_to_deploy(app_path: Path, app_name: str) -> tuple[Optional[bool], str]:
    """Agent Metric: Actually invoke agent to deploy this app (Binary)"""
    prompt = f"""You are evaluating the deployability of the application "{app_name}".

Your task:
1. Check if Dockerfile exists
2. Attempt to build the Docker image
3. Check if app.yaml exists and is valid for Databricks Apps deployment
4. Verify the deployment configuration is complete

Working directory: {app_path}

Important:
- Actually execute docker build commands using available tools
- Validate app.yaml structure if present
- Report success only if Docker builds successfully AND app.yaml is valid
- Do not push to any registry or deploy to production

Please proceed with verifying the deployment configuration and report the results."""

    return asyncio.run(_run_agent_task(prompt, "deploy", app_path))


def evaluate_local_runability(app_path: Path) -> tuple[int, List[str]]:
    """Metric 8: LOCAL RUNABILITY (Score 0-5)"""
    score = 0
    details = []

    # README (1 point)
    if check_file_exists(app_path, "README.md"):
        score += 1
        details.append("✓ Has README.md")
    else:
        details.append("✗ Missing README.md")

    # .env.example (1 point)
    if check_file_exists(app_path, ".env.example"):
        score += 1
        details.append("✓ Has .env.example")
    else:
        details.append("✗ Missing .env.example")

    # Install works (1 point)
    if check_file_exists(app_path, "package.json"):
        code, _, _ = run_command("npm install", str(app_path), timeout=120)
        if code == 0:
            score += 1
            details.append("✓ Install works (npm)")
        else:
            details.append("✗ Install failed (npm)")
    elif check_file_exists(app_path, "requirements.txt"):
        code, _, _ = run_command("pip install -r requirements.txt", str(app_path), timeout=120)
        if code == 0:
            score += 1
            details.append("✓ Install works (pip)")
        else:
            details.append("✗ Install failed (pip)")

    # Run command exists (1 point)
    has_run = False
    if check_file_exists(app_path, "package.json"):
        try:
            with open(app_path / "package.json") as f:
                pkg = json.load(f)
                if "scripts" in pkg and ("start" in pkg["scripts"] or "dev" in pkg["scripts"]):
                    score += 1
                    details.append("✓ Has run command")
                    has_run = True
        except:
            pass
    elif check_file_exists(app_path, "app.py") or check_file_exists(app_path, "main.py"):
        score += 1
        details.append("✓ Has run command (Streamlit)")
        has_run = True

    if not has_run:
        details.append("✗ No run command")

    # Starts successfully (1 point) - already evaluated in runtime_success
    # We'll leave this for now
    details.append("○ Start success evaluated separately")

    return score, details


def evaluate_deployability(app_path: Path) -> tuple[int, List[str]]:
    """Metric 9: DEPLOYABILITY (Score 0-5)"""
    score = 0
    details = []

    # Dockerfile (1 point)
    if check_file_exists(app_path, "Dockerfile"):
        score += 1
        details.append("✓ Has Dockerfile")

        # Multi-stage build (1 point)
        try:
            with open(app_path / "Dockerfile") as f:
                content = f.read()
                if "FROM" in content and content.count("FROM") > 1:
                    score += 1
                    details.append("✓ Multi-stage build")
                else:
                    details.append("✗ Not multi-stage build")

                # Health check (1 point)
                if "HEALTHCHECK" in content:
                    score += 1
                    details.append("✓ Has health check")
                else:
                    details.append("✗ No health check")

                # No hardcoded secrets (1 point)
                suspicious = ["password=", "token=", "secret=", "api_key="]
                has_hardcoded = any(s in content.lower() for s in suspicious)
                if not has_hardcoded:
                    score += 1
                    details.append("✓ No hardcoded secrets")
                else:
                    details.append("✗ Possible hardcoded secrets")
        except:
            details.append("✗ Could not read Dockerfile")
    else:
        details.append("✗ Missing Dockerfile")
        details.append("✗ No multi-stage build")
        details.append("✗ No health check")
        details.append("✗ No hardcoded secrets check")

    # app.yaml (1 point)
    if check_file_exists(app_path, "app.yaml"):
        score += 1
        details.append("✓ Has app.yaml")
    else:
        details.append("✗ Missing app.yaml")

    return score, details


def evaluate_app(app_name: str, enable_agent_metrics: bool = False) -> Dict[str, Any]:
    """Evaluate a single app using all 9 metrics."""
    print(f"\n{'='*60}")
    print(f"Evaluating: {app_name}")
    print(f"{'='*60}")

    app_path = APP_DIR / app_name
    result = {
        "app_name": app_name,
        "metrics": {},
        "issues": []
    }

    # Metric 1: Build Success
    print("1. Checking build success...")
    build_success, build_msg = evaluate_build_success(app_path, app_name)
    result["metrics"]["build_success"] = build_success
    result["issues"].append(f"Build: {build_msg}")
    print(f"   {'✓' if build_success else '✗'} {build_msg}")

    # Metric 2: Runtime Success
    print("2. Checking runtime success...")
    runtime_success, runtime_msg = evaluate_runtime_success(app_path, app_name)
    result["metrics"]["runtime_success"] = runtime_success
    result["issues"].append(f"Runtime: {runtime_msg}")
    print(f"   {'✓' if runtime_success else '✗'} {runtime_msg}")

    # Metric 3: Type Safety
    print("3. Checking type safety...")
    type_safety, type_msg = evaluate_type_safety(app_path)
    result["metrics"]["type_safety"] = type_safety
    result["issues"].append(f"Type Safety: {type_msg}")
    print(f"   {('✓' if type_safety else '✗') if type_safety is not None else 'N/A'} {type_msg}")

    # Metric 4: Tests Pass
    print("4. Checking tests...")
    tests_pass, coverage, tests_msg = evaluate_tests_pass(app_path)
    result["metrics"]["tests_pass"] = tests_pass
    result["metrics"]["test_coverage"] = coverage
    result["issues"].append(f"Tests: {tests_msg}")
    print(f"   {('✓' if tests_pass else '✗') if tests_pass is not None else 'N/A'} {tests_msg}")

    # Metric 5: Databricks Connectivity
    print("5. Checking Databricks connectivity...")
    db_conn, db_msg = evaluate_databricks_connectivity(app_path)
    result["metrics"]["databricks_connectivity"] = db_conn
    result["issues"].append(f"Databricks: {db_msg}")
    print(f"   {'✓' if db_conn else '✗'} {db_msg}")

    # Metric 6: Data Returned (Not implemented)
    result["metrics"]["data_returned"] = None
    print("6. Data returned: Not implemented")

    # Metric 7: UI Renders (VLM-based)
    print("7. Checking UI renders (VLM-based)...")
    ui_renders, ui_msg = evaluate_ui_renders(app_path, app_name)
    result["metrics"]["ui_renders"] = ui_renders
    result["issues"].append(f"UI Renders: {ui_msg}")
    print(f"   {('✓' if ui_renders else '✗') if ui_renders is not None else 'N/A'} {ui_msg}")

    # Metric 8: Local Runability
    print("8. Checking local runability...")
    runability_score, runability_details = evaluate_local_runability(app_path)
    result["metrics"]["local_runability_score"] = runability_score
    result["metrics"]["local_runability_details"] = runability_details
    print(f"   Score: {runability_score}/5")
    for detail in runability_details:
        print(f"      {detail}")

    # Metric 9: Deployability
    print("9. Checking deployability...")
    deploy_score, deploy_details = evaluate_deployability(app_path)
    result["metrics"]["deployability_score"] = deploy_score
    result["metrics"]["deployability_details"] = deploy_details
    print(f"   Score: {deploy_score}/5")
    for detail in deploy_details:
        print(f"      {detail}")

    # Agent-Based Complementary Metrics (optional, controlled by --enable-agent-metrics flag)
    if enable_agent_metrics:
        print("\n=== Agent-Based Metrics ===")

        # Agent Metric 1: Can agent build?
        print("A1. Invoking agent to build...")
        agent_build, agent_build_msg = invoke_agent_to_build(app_path, app_name)
        result["metrics"]["agent_build_success"] = agent_build
        result["issues"].append(f"Agent Build: {agent_build_msg}")
        print(f"    {('✓' if agent_build else '✗') if agent_build is not None else 'N/A'} {agent_build_msg}")

        # Agent Metric 2: Can agent run?
        print("A2. Invoking agent to run...")
        agent_run, agent_run_msg = invoke_agent_to_run(app_path, app_name)
        result["metrics"]["agent_run_success"] = agent_run
        result["issues"].append(f"Agent Run: {agent_run_msg}")
        print(f"    {('✓' if agent_run else '✗') if agent_run is not None else 'N/A'} {agent_run_msg}")

        # Agent Metric 3: Can agent test?
        print("A3. Invoking agent to test...")
        agent_test, agent_test_msg = invoke_agent_to_test(app_path, app_name)
        result["metrics"]["agent_test_success"] = agent_test
        result["issues"].append(f"Agent Test: {agent_test_msg}")
        print(f"    {('✓' if agent_test else '✗') if agent_test is not None else 'N/A'} {agent_test_msg}")

        # Agent Metric 4: Can agent deploy?
        print("A4. Invoking agent to deploy...")
        agent_deploy, agent_deploy_msg = invoke_agent_to_deploy(app_path, app_name)
        result["metrics"]["agent_deploy_success"] = agent_deploy
        result["issues"].append(f"Agent Deploy: {agent_deploy_msg}")
        print(f"    {('✓' if agent_deploy else '✗') if agent_deploy is not None else 'N/A'} {agent_deploy_msg}")
    else:
        # Agent metrics disabled
        result["metrics"]["agent_build_success"] = None
        result["metrics"]["agent_run_success"] = None
        result["metrics"]["agent_test_success"] = None
        result["metrics"]["agent_deploy_success"] = None

    return result


def generate_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate summary statistics."""
    total_apps = len(results)

    # Count successes for direct execution metrics
    build_success_count = sum(1 for r in results if r["metrics"].get("build_success"))
    runtime_success_count = sum(1 for r in results if r["metrics"].get("runtime_success"))
    type_safety_count = sum(1 for r in results if r["metrics"].get("type_safety") is True)
    type_safety_na_count = sum(1 for r in results if r["metrics"].get("type_safety") is None)
    tests_pass_count = sum(1 for r in results if r["metrics"].get("tests_pass") is True)
    tests_na_count = sum(1 for r in results if r["metrics"].get("tests_pass") is None)
    databricks_count = sum(1 for r in results if r["metrics"].get("databricks_connectivity"))
    ui_renders_count = sum(1 for r in results if r["metrics"].get("ui_renders") is True)
    ui_renders_na_count = sum(1 for r in results if r["metrics"].get("ui_renders") is None)

    # Count successes for agent-based metrics
    agent_build_count = sum(1 for r in results if r["metrics"].get("agent_build_success") is True)
    agent_build_na_count = sum(1 for r in results if r["metrics"].get("agent_build_success") is None)
    agent_run_count = sum(1 for r in results if r["metrics"].get("agent_run_success") is True)
    agent_run_na_count = sum(1 for r in results if r["metrics"].get("agent_run_success") is None)
    agent_test_count = sum(1 for r in results if r["metrics"].get("agent_test_success") is True)
    agent_test_na_count = sum(1 for r in results if r["metrics"].get("agent_test_success") is None)
    agent_deploy_count = sum(1 for r in results if r["metrics"].get("agent_deploy_success") is True)
    agent_deploy_na_count = sum(1 for r in results if r["metrics"].get("agent_deploy_success") is None)

    # Average scores
    avg_runability = sum(r["metrics"].get("local_runability_score", 0) for r in results) / total_apps
    avg_deployability = sum(r["metrics"].get("deployability_score", 0) for r in results) / total_apps

    return {
        "total_apps": total_apps,
        "metrics_summary": {
            "build_success": f"{build_success_count}/{total_apps}",
            "runtime_success": f"{runtime_success_count}/{total_apps}",
            "type_safety": f"{type_safety_count}/{total_apps - type_safety_na_count} (N/A: {type_safety_na_count})",
            "tests_pass": f"{tests_pass_count}/{total_apps - tests_na_count} (N/A: {tests_na_count})",
            "databricks_connectivity": f"{databricks_count}/{total_apps}",
            "data_returned": "Not implemented",
            "ui_renders": f"{ui_renders_count}/{total_apps - ui_renders_na_count} (N/A: {ui_renders_na_count})",
            "local_runability_avg": f"{avg_runability:.2f}/5",
            "deployability_avg": f"{avg_deployability:.2f}/5",
            "agent_build_success": f"{agent_build_count}/{total_apps - agent_build_na_count} (N/A: {agent_build_na_count})",
            "agent_run_success": f"{agent_run_count}/{total_apps - agent_run_na_count} (N/A: {agent_run_na_count})",
            "agent_test_success": f"{agent_test_count}/{total_apps - agent_test_na_count} (N/A: {agent_test_na_count})",
            "agent_deploy_success": f"{agent_deploy_count}/{total_apps - agent_deploy_na_count} (N/A: {agent_deploy_na_count})"
        }
    }


def generate_markdown_report(summary: Dict[str, Any], results: List[Dict[str, Any]]) -> str:
    """Generate markdown report."""
    md = "# Evaluation Report\n\n"
    md += f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    md += "## Summary\n\n"
    md += f"- **Total Apps Evaluated:** {summary['total_apps']}\n\n"

    md += "### Metrics Overview\n\n"
    for metric, value in summary["metrics_summary"].items():
        md += f"- **{metric.replace('_', ' ').title()}:** {value}\n"

    md += "\n## Individual App Results\n\n"

    for result in results:
        app_name = result["app_name"]
        metrics = result["metrics"]

        md += f"### {app_name}\n\n"

        # Binary metrics
        md += "**Binary Metrics:**\n"
        md += f"- Build Success: {'✓' if metrics.get('build_success') else '✗'}\n"
        md += f"- Runtime Success: {'✓' if metrics.get('runtime_success') else '✗'}\n"

        type_safety = metrics.get('type_safety')
        md += f"- Type Safety: {('✓' if type_safety else '✗') if type_safety is not None else 'N/A'}\n"

        tests_pass = metrics.get('tests_pass')
        md += f"- Tests Pass: {('✓' if tests_pass else '✗') if tests_pass is not None else 'N/A'}\n"

        md += f"- Databricks Connectivity: {'✓' if metrics.get('databricks_connectivity') else '✗'}\n"
        md += f"- Data Returned: N/A (not implemented)\n"
        md += f"- UI Renders: N/A (not implemented)\n\n"

        # Scored metrics
        md += "**Scored Metrics:**\n"
        md += f"- Local Runability: {metrics.get('local_runability_score', 0)}/5\n"
        for detail in metrics.get('local_runability_details', []):
            md += f"  - {detail}\n"

        md += f"- Deployability: {metrics.get('deployability_score', 0)}/5\n"
        for detail in metrics.get('deployability_details', []):
            md += f"  - {detail}\n"

        md += "\n**Issues:**\n"
        for issue in result["issues"]:
            md += f"- {issue}\n"

        md += "\n---\n\n"

    return md


def main(enable_agent_metrics: bool = False):
    """Main evaluation function."""
    # Get list of apps
    apps = [d for d in os.listdir(APP_DIR) if (APP_DIR / d).is_dir()]
    apps = sorted(apps)

    print(f"Found {len(apps)} apps to evaluate")

    if enable_agent_metrics:
        print("⚠️  Agent-based metrics ENABLED (slow, ~2-3 min per app)")
    else:
        print("ℹ️  Agent-based metrics DISABLED (use --enable-agent-metrics to enable)")

    # Evaluate each app
    results = []
    for app_name in apps:
        try:
            result = evaluate_app(app_name, enable_agent_metrics=enable_agent_metrics)
            results.append(result)
        except Exception as e:
            print(f"ERROR evaluating {app_name}: {e}")
            results.append({
                "app_name": app_name,
                "metrics": {},
                "issues": [f"Evaluation error: {str(e)}"]
            })

    # Generate summary
    summary = generate_summary(results)

    # Save JSON report
    report = {
        "summary": summary,
        "apps": results
    }

    with open("evaluation_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\n✓ Saved evaluation_report.json")

    # Save Markdown report
    md_report = generate_markdown_report(summary, results)
    with open("EVALUATION_REPORT.md", "w") as f:
        f.write(md_report)
    print("✓ Saved EVALUATION_REPORT.md")

    # Track evaluation in MLflow
    try:
        from mlflow_tracker import EvaluationTracker
        from datetime import datetime, timezone

        # Determine mode from environment or default to "manual"
        mode = os.environ.get("EVAL_MODE", "manual")

        tracker = EvaluationTracker()
        if tracker.enabled:
            timestamp = datetime.now(timezone.utc).isoformat()
            run_name = f"eval_{mode}_{timestamp}"

            run_id = tracker.start_run(run_name, tags={"mode": mode})

            if run_id:
                # Log parameters
                tracker.log_evaluation_parameters(
                    mode=mode,
                    total_apps=summary['total_apps'],
                    timestamp=timestamp,
                    model_version="claude-sonnet-4-5-20250929"
                )

                # Log metrics
                tracker.log_evaluation_metrics(report)

                # Log artifacts
                tracker.log_artifact_file("evaluation_report.json")
                tracker.log_artifact_file("EVALUATION_REPORT.md")

                # End run
                tracker.end_run()

                print(f"✓ MLflow tracking: {run_id}")
    except Exception as e:
        print(f"⚠️  MLflow tracking failed: {e}")

    print(f"\nEvaluation complete! Evaluated {len(results)} apps.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Evaluate generated apps with objective metrics'
    )
    parser.add_argument(
        '--enable-agent-metrics',
        action='store_true',
        default=False,
        help='Enable agent-based metrics (slow, ~2-3 min per app, adds ~$0.20/app cost)'
    )
    args = parser.parse_args()

    main(enable_agent_metrics=args.enable_agent_metrics)
