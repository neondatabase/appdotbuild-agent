"""TypeScript Workspace Factory for Dagger-based Evaluation

This module provides utilities to create Dagger workspaces configured for
evaluating TypeScript applications (tRPC, DBX-SDK, or Docker-based).
"""

from pathlib import Path
import dagger

from cli.utils.workspace import Workspace
from cli.utils.dagger_utils import ExecResult


async def create_ts_workspace(
    client: dagger.Client,
    app_dir: Path,
    template: str,
    port: int,
) -> Workspace:
    """Create a Dagger workspace for TypeScript app evaluation.

    Args:
        client: Dagger client connection
        app_dir: Path to the app directory on host
        template: Template type (trpc, dbx-sdk, or docker)
        port: Port to expose for the app (e.g., 8000, 8001, etc.)

    Returns:
        Workspace configured with Node.js, app files, and eval scripts
    """

    # Load app directory as Dagger Directory (exclude node_modules to force clean install)
    app_context = client.host().directory(
        str(app_dir),
        exclude=["node_modules", "**/node_modules", "**/.next", "**/dist", "**/build"]
    )

    # Choose base image - Node.js 20 Alpine for speed and size
    base_image = "node:20-alpine"

    # Setup commands to install required tools
    setup_cmds = [
        # Install bash and curl for running scripts and health checks
        ["apk", "add", "--no-cache", "bash", "curl"],
    ]

    # Create workspace with app directory mounted
    workspace = await Workspace.create(
        client=client,
        base_image=base_image,
        context=app_context,
        setup_cmd=setup_cmds,
    )

    # Copy all eval scripts into container
    eval_dir = Path(__file__).parent.parent / "eval" / template

    # Copy all .sh files from eval directory
    if eval_dir.exists():
        for script_path in eval_dir.glob("*.sh"):
            script_name = script_path.name
            content = script_path.read_text()
            workspace = workspace.write_file(f"/eval/{script_name}", content, force=True)

    # Set environment variables for evaluation
    import os

    # Pass Databricks credentials from host environment or SDK auto-auth
    databricks_host = os.getenv("DATABRICKS_HOST", "")
    databricks_token = os.getenv("DATABRICKS_TOKEN", "")
    databricks_warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")

    # Try to get credentials from SDK if not set (works for both PAT and OAuth)
    if not databricks_host or not databricks_token:
        try:
            from databricks.sdk import WorkspaceClient
            ws_client = WorkspaceClient()
            ws_config = ws_client.config
            if not databricks_host and ws_config.host:
                databricks_host = ws_config.host
            if not databricks_token:
                # Try PAT first, then OAuth token extraction
                if ws_config.token:
                    databricks_token = ws_config.token
                else:
                    # Extract token from OAuth auth headers
                    headers = ws_config.authenticate()
                    auth_header = headers.get("Authorization", "")
                    if auth_header.startswith("Bearer "):
                        databricks_token = auth_header[7:]
        except Exception:
            pass  # SDK auto-auth not available

    if databricks_host:
        workspace.ctr = workspace.ctr.with_env_variable("DATABRICKS_HOST", databricks_host)
    if databricks_token:
        workspace.ctr = workspace.ctr.with_env_variable("DATABRICKS_TOKEN", databricks_token)
    if databricks_warehouse_id:
        workspace.ctr = workspace.ctr.with_env_variable("DATABRICKS_WAREHOUSE_ID", databricks_warehouse_id)

    workspace.ctr = workspace.ctr.with_env_variable("DATABRICKS_APP_PORT", str(port))
    workspace.ctr = workspace.ctr.with_env_variable("DATABRICKS_APP_NAME", app_dir.name)
    workspace.ctr = workspace.ctr.with_env_variable("FLASK_RUN_HOST", "0.0.0.0")
    # Note: Don't set DATABRICKS_CLIENT_ID/SECRET when using PAT auth (DATABRICKS_TOKEN)
    # The Databricks SDK doesn't allow mixing OAuth and PAT auth methods

    # Expose port for health checks
    workspace.ctr = workspace.ctr.with_exposed_port(port)

    return workspace


async def install_dependencies(workspace: Workspace) -> ExecResult:
    """Install npm dependencies using install.sh script.

    Args:
        workspace: Configured TypeScript workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    # Use update_ctr=True to persist node_modules in the container
    return await workspace.exec(["bash", "/eval/install.sh"], update_ctr=True)


async def build_app(workspace: Workspace) -> ExecResult:
    """Build the app using build.sh script.

    Args:
        workspace: Configured TypeScript workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    # Use update_ctr=True to persist build output (dist/) in the container
    return await workspace.exec(["bash", "/eval/build.sh"], update_ctr=True)


async def check_runtime(workspace: Workspace) -> ExecResult:
    """Check if the server can start without immediate errors.

    Uses the template-specific start.sh script which handles:
    - Starting the server via npm start
    - Health checking the endpoints
    - Proper cleanup

    Args:
        workspace: Configured TypeScript workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    import time
    # Add cache-busting env var to force Dagger to re-run the command
    # Without this, Dagger caches the result and returns it instantly
    workspace.ctr = workspace.ctr.with_env_variable("_EVAL_TIMESTAMP", str(time.time()))
    # Use the start.sh script which handles npm start and health checks
    result = await workspace.exec(["bash", "/eval/start.sh"])
    return result


async def run_tests(workspace: Workspace, test_port: int, fast_mode: bool = False) -> ExecResult:
    """Run tests using test.sh script.

    Args:
        workspace: Configured TypeScript workspace
        test_port: Port to use for test server (to avoid conflicts)
        fast_mode: If True, skip smoke tests and run only unit tests

    Returns:
        ExecResult with exit code, stdout, stderr (includes coverage output)
    """
    # Set TEST_PORT env var for tests
    workspace.ctr = workspace.ctr.with_env_variable("TEST_PORT", str(test_port))
    # Set EVAL_FAST_MODE to control whether smoke tests are skipped
    if fast_mode:
        workspace.ctr = workspace.ctr.with_env_variable("EVAL_FAST_MODE", "true")
    # Run tests using test.sh script
    return await workspace.exec(["bash", "/eval/test.sh"])


async def check_types(workspace: Workspace) -> ExecResult:
    """Run TypeScript type checking using typecheck.sh script.

    Args:
        workspace: Configured TypeScript workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    return await workspace.exec(["bash", "/eval/typecheck.sh"])


async def capture_screenshot(
    workspace: Workspace,
    app_dir: Path,
    port: int = 8000,
    wait_time: int = 10000,
) -> bool:
    """Capture a screenshot of the running app using Playwright.

    Starts the app as a Dagger service, runs Playwright to capture a screenshot,
    and exports it to the app directory.

    Args:
        workspace: Configured TypeScript workspace with built app
        app_dir: Path to export screenshot to
        port: Port the app listens on
        wait_time: Milliseconds to wait for network idle

    Returns:
        True if screenshot was captured successfully
    """
    import time

    client = workspace.client

    # Create app service - runs npm start and stays running
    # Using a shell command that starts the app in background and waits
    app_service = (
        workspace.ctr
        .with_env_variable("_SCREENSHOT_TIMESTAMP", str(time.time()))
        .with_exec(
            ["sh", "-c", "cd /app && npm start"],
            expect=dagger.ReturnType.ANY,
        )
        .with_exposed_port(port)
        .as_service()
    )

    # Create Playwright container
    playwright_ctr = (
        client.container()
        .from_("mcr.microsoft.com/playwright:v1.40.0-jammy")
        .with_service_binding("app", app_service)
        .with_workdir("/work")
        .with_new_file(
            "/work/screenshot.js",
            f"""
const {{ chromium }} = require('playwright');

(async () => {{
    const browser = await chromium.launch();
    const page = await browser.newPage();
    try {{
        await page.goto('http://app:{port}', {{
            waitUntil: 'networkidle',
            timeout: {wait_time}
        }});
        await page.screenshot({{ path: '/work/screenshot.png', fullPage: true }});
        console.log('Screenshot captured successfully');
    }} catch (e) {{
        console.error('Screenshot failed:', e.message);
        // Take screenshot anyway to capture error state
        await page.screenshot({{ path: '/work/screenshot.png', fullPage: true }});
    }} finally {{
        await browser.close();
    }}
}})();
""",
        )
    )

    try:
        # Run the screenshot script
        result_ctr = await playwright_ctr.with_exec(
            ["node", "/work/screenshot.js"],
            expect=dagger.ReturnType.ANY,
        ).sync()

        # Export screenshot to host
        screenshot_dir = app_dir / "screenshot_output"
        screenshot_dir.mkdir(exist_ok=True)

        screenshot_file = result_ctr.file("/work/screenshot.png")
        await screenshot_file.export(str(screenshot_dir / "screenshot.png"))

        print("    ✅ Screenshot captured")
        return True

    except Exception as e:
        print(f"    ⚠️  Screenshot failed: {e}")
        return False
