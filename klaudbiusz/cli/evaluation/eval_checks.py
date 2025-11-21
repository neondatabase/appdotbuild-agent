"""Shared evaluation check functions for Klaudbiusz evaluation framework."""

import json
from pathlib import Path
from typing import Callable


def check_databricks_connectivity(
    app_dir: Path,
    port: int,
    run_command: Callable,
    template: str = "trpc",
) -> bool:
    """
    Check if app can connect to Databricks and execute queries.

    Args:
        app_dir: Path to the app directory
        port: Port where the app is running (8000 or 3000)
        run_command: Function to execute shell commands (success, stdout, stderr)
        template: Template type ("trpc", "dbx-sdk", or "unknown")

    Returns:
        True if Databricks connectivity works, False otherwise
    """
    if template == "dbx-sdk":
        return _check_dbx_sdk_connectivity(app_dir, port, run_command)
    elif template == "trpc":
        return _check_trpc_connectivity(app_dir, port, run_command)
    else:
        # Try both methods for unknown templates
        return (
            _check_trpc_connectivity(app_dir, port, run_command)
            or _check_dbx_sdk_connectivity(app_dir, port, run_command)
        )


def _check_trpc_connectivity(app_dir: Path, port: int, run_command: Callable) -> bool:
    """Check tRPC-based app connectivity."""
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


def _check_dbx_sdk_connectivity(app_dir: Path, port: int, run_command: Callable) -> bool:
    """Check DBX SDK-based app connectivity."""
    # Look for SQL query files in config/queries/
    queries_dir = app_dir / "config" / "queries"
    if not queries_dir.exists():
        return False

    sql_files = list(queries_dir.glob("*.sql"))
    if not sql_files:
        return False

    # Try calling analytics API endpoints
    for sql_file in sql_files[:3]:  # Try first 3 queries
        query_key = sql_file.stem  # Filename without .sql extension

        # Try POST request to analytics endpoint
        success, stdout, _ = run_command(
            [
                "curl",
                "-f",
                "-s",
                "-X",
                "POST",
                f"http://localhost:{port}/api/analytics/{query_key}",
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
                # Check if we got data back (array or object with data)
                if result and (isinstance(result, list) or isinstance(result, dict)):
                    return True
            except json.JSONDecodeError:
                pass

    return False


def extract_sql_queries(app_dir: Path, template: str = "trpc") -> list[str]:
    """
    Extract SQL queries from the app.

    Args:
        app_dir: Path to the app directory
        template: Template type ("trpc", "dbx-sdk", or "unknown")

    Returns:
        List of SQL query strings
    """
    if template == "dbx-sdk":
        return _extract_dbx_sdk_queries(app_dir)
    elif template == "trpc":
        return _extract_trpc_queries(app_dir)
    else:
        # Try both methods
        queries = _extract_trpc_queries(app_dir)
        if not queries:
            queries = _extract_dbx_sdk_queries(app_dir)
        return queries


def _extract_trpc_queries(app_dir: Path) -> list[str]:
    """Extract inline SQL queries from tRPC app."""
    queries = []

    # Look in server/src/ for TypeScript files
    server_src = app_dir / "server" / "src"
    if not server_src.exists():
        return queries

    for ts_file in server_src.glob("**/*.ts"):
        content = ts_file.read_text()
        # Look for SQL queries in template literals
        if "query = `" in content or "query=`" in content:
            # Simple extraction - get text between backticks after "query"
            parts = content.split("query")
            for part in parts[1:]:
                if part.strip().startswith("="):
                    rest = part[part.index("=") + 1 :].strip()
                    if rest.startswith("`"):
                        # Find matching backtick
                        end = rest.find("`", 1)
                        if end > 0:
                            query = rest[1:end]
                            if query.strip():
                                queries.append(query)

    return queries


def _extract_dbx_sdk_queries(app_dir: Path) -> list[str]:
    """Extract SQL queries from DBX SDK app (separate .sql files)."""
    queries = []

    queries_dir = app_dir / "config" / "queries"
    if not queries_dir.exists():
        return queries

    for sql_file in queries_dir.glob("*.sql"):
        content = sql_file.read_text()
        if content.strip():
            queries.append(content)

    return queries
