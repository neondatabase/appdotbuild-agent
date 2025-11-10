"""
Template detection for Databricks applications.

Automatically identifies which template/SDK was used to generate an app
by examining the app structure and key files.
"""

from pathlib import Path


def detect_template(app_dir: Path) -> str:
    """
    Detect which template was used to generate the app.

    Args:
        app_dir: Path to the application directory

    Returns:
        Template type: "dbx-sdk", "trpc", or "unknown"
    """
    # DBX SDK markers (new template)
    if _is_dbx_sdk_app(app_dir):
        return "dbx-sdk"

    # tRPC markers (legacy template)
    if _is_trpc_app(app_dir):
        return "trpc"

    return "unknown"


def _is_dbx_sdk_app(app_dir: Path) -> bool:
    """Check if app uses DBX SDK template."""
    score = 0

    # Check backend/index.ts for @dbx/sdk
    backend_index = app_dir / "backend" / "index.ts"
    if backend_index.exists():
        content = backend_index.read_text()
        if "@dbx/sdk" in content or "DBX.init" in content:
            score += 2

    # Check for SQL queries directory
    queries_dir = app_dir / "config" / "queries"
    if queries_dir.exists() and queries_dir.is_dir():
        sql_files = list(queries_dir.glob("*.sql"))
        if sql_files:
            score += 2

    # Check for app.yaml
    if (app_dir / "app.yaml").exists():
        score += 1

    # Check for DBX SDK tarball
    if list(app_dir.glob("dbx-sdk-*.tgz")):
        score += 1

    # Need at least 2 indicators for confident detection
    return score >= 2


def _is_trpc_app(app_dir: Path) -> bool:
    """Check if app uses tRPC template."""
    score = 0

    # Check for server/src/index.ts with tRPC
    server_index = app_dir / "server" / "src" / "index.ts"
    if server_index.exists():
        content = server_index.read_text()
        if "@trpc/server" in content or "publicProcedure" in content:
            score += 2

    # Check for server/ directory with package.json
    if (app_dir / "server" / "package.json").exists():
        score += 1

    # Check for client/ directory
    if (app_dir / "client").exists() and (app_dir / "client").is_dir():
        score += 1

    # Check for Drizzle ORM
    server_db = app_dir / "server" / "src" / "db"
    if server_db.exists() and server_db.is_dir():
        score += 1

    # Need at least 2 indicators for confident detection
    return score >= 2


def get_template_info(template: str) -> dict:
    """
    Get template-specific configuration.

    Args:
        template: Template type ("dbx-sdk", "trpc", or "unknown")

    Returns:
        Dictionary with template-specific paths and patterns
    """
    if template == "dbx-sdk":
        return {
            "backend_dirs": ["backend"],
            "frontend_dirs": ["frontend"],
            "entry_points": ["backend/index.ts"],
            "package_json_location": "root",
            "api_pattern": "/api/analytics/{query_key}",
            "sql_location": "config/queries/*.sql",
        }
    elif template == "trpc":
        return {
            "backend_dirs": ["server"],
            "frontend_dirs": ["client"],
            "entry_points": ["server/src/index.ts", "server/index.ts"],
            "package_json_location": "split",  # Separate server/ and client/
            "api_pattern": "/api/trpc/{procedure}",
            "sql_location": "inline",  # SQL embedded in TypeScript
        }
    else:
        # Fallback: try all common patterns
        return {
            "backend_dirs": ["backend", "server", "api"],
            "frontend_dirs": ["frontend", "client"],
            "entry_points": ["backend/index.ts", "server/src/index.ts", "server/index.ts", "src/index.ts"],
            "package_json_location": "unknown",
            "api_pattern": "unknown",
            "sql_location": "unknown",
        }
