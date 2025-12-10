"""
Apps directory discovery utilities.

Supports UC Volumes pattern with latest.txt pointer files.

Usage:
    from cli.utils.apps_discovery import find_latest_apps_dir

    # Find apps from UC Volume
    apps_dir = find_latest_apps_dir("/Volumes/main/default/apps_mcp_generated")

    # Find apps from local path
    apps_dir = find_latest_apps_dir("./app")
"""

from pathlib import Path


def find_latest_apps_dir(volume_path: str | Path) -> Path | None:
    """Find latest apps directory from UC Volume or local path.

    Supports:
    - latest.txt pointer file (UC Volumes pattern)
    - Most recent run_* directory
    - Direct path to apps (if contains package.json files)

    Args:
        volume_path: Path to UC Volume or local directory containing apps.

    Returns:
        Path to apps directory, or None if not found.

    Example:
        # UC Volume with latest.txt
        apps = find_latest_apps_dir("/Volumes/main/default/apps")
        # Returns: /Volumes/main/default/apps/run_20240115_143022

        # Local directory with run_* dirs
        apps = find_latest_apps_dir("./generated")
        # Returns: ./generated/run_20240115_143022

        # Direct path to apps
        apps = find_latest_apps_dir("./app")
        # Returns: ./app
    """
    volume_path = Path(volume_path)

    if not volume_path.exists():
        return None

    # Check for latest.txt pointer file (UC Volumes pattern)
    latest_file = volume_path / "latest.txt"
    if latest_file.exists():
        try:
            latest_path = Path(latest_file.read_text().strip())
            if latest_path.exists():
                return latest_path
        except Exception:
            pass

    # Find most recent run_* directory
    run_dirs = [d for d in volume_path.iterdir() if d.is_dir() and d.name.startswith("run_")]
    if run_dirs:
        return max(run_dirs, key=lambda d: d.name)

    # Check if this is a direct path to apps (contains subdirs with package.json)
    if any(volume_path.glob("*/package.json")):
        return volume_path

    return None


def list_apps_in_dir(apps_dir: str | Path) -> list[Path]:
    """List all app directories in a given path.

    Args:
        apps_dir: Path to directory containing apps.

    Returns:
        Sorted list of app directory paths.
    """
    apps_dir = Path(apps_dir)
    if not apps_dir.exists():
        return []

    excluded_dirs = {"logs", "node_modules", "__pycache__", ".git"}
    return sorted(
        d
        for d in apps_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in excluded_dirs
    )


__all__ = [
    "find_latest_apps_dir",
    "list_apps_in_dir",
]
