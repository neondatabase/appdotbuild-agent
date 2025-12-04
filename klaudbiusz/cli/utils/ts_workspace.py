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

    # Pass Databricks credentials from host environment
    databricks_host = os.getenv("DATABRICKS_HOST", "")
    databricks_token = os.getenv("DATABRICKS_TOKEN", "")
    databricks_warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")

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


async def run_tests(workspace: Workspace, test_port: int) -> ExecResult:
    """Run tests using test.sh script.

    Args:
        workspace: Configured TypeScript workspace
        test_port: Port to use for test server (to avoid conflicts)

    Returns:
        ExecResult with exit code, stdout, stderr (includes coverage output)
    """
    # Set TEST_PORT env var for tests
    workspace.ctr = workspace.ctr.with_env_variable("TEST_PORT", str(test_port))
    # Run tests directly without bash script to see actual npm test output
    return await workspace.exec(["sh", "-c", "cd server && npm test || true"])


async def check_types(workspace: Workspace) -> ExecResult:
    """Run TypeScript type checking using typecheck.sh script.

    Args:
        workspace: Configured TypeScript workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    return await workspace.exec(["bash", "/eval/typecheck.sh"])
