"""TypeScript Workspace Factory for Docker-based Evaluation (no Dagger).

This module provides utilities to create Docker workspaces configured for
evaluating TypeScript applications, using plain docker CLI instead of Dagger.
"""

import os
from pathlib import Path

from cli.utils.docker_workspace import DockerWorkspace
from cli.utils.dagger_utils import ExecResult


def create_ts_workspace_docker(
    app_dir: Path,
    template: str,
    port: int,
) -> DockerWorkspace:
    """Create a Docker workspace for TypeScript app evaluation.

    Args:
        app_dir: Path to the app directory on host
        template: Template type (trpc, dbx-sdk, or docker)
        port: Port to expose for the app (e.g., 8000, 8001, etc.)

    Returns:
        DockerWorkspace configured with Node.js, app files, and eval scripts
    """
    # Prepare environment variables
    env_vars = {
        "DATABRICKS_HOST": os.getenv("DATABRICKS_HOST", ""),
        "DATABRICKS_TOKEN": os.getenv("DATABRICKS_TOKEN", ""),
        "DATABRICKS_WAREHOUSE_ID": os.getenv("DATABRICKS_WAREHOUSE_ID", ""),
        "DATABRICKS_APP_PORT": str(port),
        "DATABRICKS_APP_NAME": app_dir.name,
        "FLASK_RUN_HOST": "0.0.0.0",
    }

    # Create workspace
    workspace = DockerWorkspace.create(
        app_dir=app_dir,
        base_image="node:20-alpine",
        port=port,
        env_vars=env_vars,
    )

    # Copy eval scripts into container
    eval_dir = Path(__file__).parent.parent / "eval" / template
    if eval_dir.exists():
        # Create /eval directory in container
        workspace.exec(["mkdir", "-p", "/eval"])

        # Copy all .sh files from eval directory
        for script_path in eval_dir.glob("*.sh"):
            workspace.copy_file(script_path, f"/eval/{script_path.name}")
            # Make executable
            workspace.exec(["chmod", "+x", f"/eval/{script_path.name}"])

    return workspace


def install_dependencies(workspace: DockerWorkspace) -> ExecResult:
    """Install npm dependencies using install.sh script.

    Args:
        workspace: Configured Docker workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    result = workspace.exec(["bash", "/eval/install.sh"], timeout=300)
    return result


def build_app(workspace: DockerWorkspace) -> ExecResult:
    """Build the application using build.sh script.

    Args:
        workspace: Configured Docker workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    result = workspace.exec(["bash", "/eval/build.sh"], timeout=300)
    return result


def check_runtime(workspace: DockerWorkspace) -> ExecResult:
    """Check if the server can start without immediate errors.

    Uses the template-specific start.sh script which handles:
    - Starting the server via npm start
    - Health checking the endpoints
    - Proper cleanup

    Args:
        workspace: Configured Docker workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    result = workspace.exec(["bash", "/eval/start.sh"], timeout=60)
    return result


def check_types(workspace: DockerWorkspace) -> ExecResult:
    """Run TypeScript type checking using typecheck.sh script.

    Args:
        workspace: Configured Docker workspace

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    result = workspace.exec(["bash", "/eval/typecheck.sh"], timeout=120)
    return result


def run_tests(workspace: DockerWorkspace, test_port: int) -> ExecResult:
    """Run tests using test.sh script.

    Args:
        workspace: Configured Docker workspace
        test_port: Port to use for test server (to avoid conflicts)

    Returns:
        ExecResult with exit code, stdout, stderr
    """
    # Set test port environment variable
    workspace.exec(["sh", "-c", f"export TEST_PORT={test_port}"])
    result = workspace.exec(["bash", "/eval/test.sh"], timeout=180)
    return result
