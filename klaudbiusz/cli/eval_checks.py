"""Shared evaluation check functions for Klaudbiusz evaluation framework."""

import json
from pathlib import Path
from typing import Callable


def check_databricks_connectivity(
    app_dir: Path,
    port: int,
    run_command: Callable,
) -> bool:
    """
    Check if app can connect to Databricks and execute queries.

    Args:
        app_dir: Path to the app directory
        port: Port where the app is running (8000 or 3000)
        run_command: Function to execute shell commands (success, stdout, stderr)

    Returns:
        True if Databricks connectivity works, False otherwise
    """
    # Discover available procedures by inspecting the router
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

    # Try first few data procedures (skip healthcheck)
    for proc in procedures[:3]:  # Try up to 3 endpoints
        # Try GET request first (standard for tRPC queries)
        success, stdout, _ = run_command(
            [
                "curl",
                "-f",
                "-s",
                f"http://localhost:{port}/api/trpc/{proc}",
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
