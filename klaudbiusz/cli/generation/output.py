"""
Generation output utilities.

Standardizes saving generated apps to UC Volumes or local directories.

Usage:
    from cli.generation.output import save_to_volume

    # Save generated apps to UC Volume
    dest = save_to_volume(
        local_dir=Path("./app"),
        volume_path="/Volumes/main/default/apps_generated",
    )
"""

import shutil
from datetime import datetime
from pathlib import Path


def save_to_volume(
    local_dir: Path,
    volume_path: str | Path,
    timestamp: str | None = None,
    exclude_patterns: list[str] | None = None,
) -> Path:
    """Save generated apps to UC Volume with timestamped directory.

    Creates:
    - {volume_path}/run_{timestamp}/
    - {volume_path}/latest.txt (pointer to latest run)

    Args:
        local_dir: Path to local directory containing generated apps.
        volume_path: Path to UC Volume or destination directory.
        timestamp: Optional timestamp string. Auto-generated if not provided.
        exclude_patterns: Optional list of directory names to exclude (default: node_modules, .next, etc.)

    Returns:
        Path to created destination directory.

    Example:
        dest = save_to_volume(
            local_dir=Path("./app"),
            volume_path="/Volumes/main/default/apps_generated",
        )
        # Creates: /Volumes/main/default/apps_generated/run_20240115_143022/
        # Updates: /Volumes/main/default/apps_generated/latest.txt
    """
    volume_path = Path(volume_path)
    timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = volume_path / f"run_{timestamp}"

    default_excludes = {
        "node_modules",
        ".next",
        "dist",
        "build",
        ".turbo",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".venv",
        "venv",
    }

    if exclude_patterns:
        default_excludes.update(exclude_patterns)

    def ignore_patterns(directory: str, files: list[str]) -> list[str]:
        return [f for f in files if f in default_excludes]

    shutil.copytree(local_dir, dest_dir, ignore=ignore_patterns)

    # Write latest pointer (symlinks not supported on UC Volumes)
    latest_file = volume_path / "latest.txt"
    latest_file.write_text(str(dest_dir))

    return dest_dir


def copy_app_to_volume(
    app_dir: Path,
    volume_path: str | Path,
    app_name: str | None = None,
) -> Path:
    """Copy a single app to a UC Volume.

    Args:
        app_dir: Path to app directory.
        volume_path: Path to UC Volume or destination directory.
        app_name: Optional app name. Uses app_dir.name if not provided.

    Returns:
        Path to copied app directory.
    """
    volume_path = Path(volume_path)
    app_name = app_name or app_dir.name
    dest_dir = volume_path / app_name

    default_excludes = {
        "node_modules",
        ".next",
        "dist",
        "build",
        ".turbo",
        "__pycache__",
    }

    def ignore_patterns(directory: str, files: list[str]) -> list[str]:
        return [f for f in files if f in default_excludes]

    if dest_dir.exists():
        shutil.rmtree(dest_dir)

    shutil.copytree(app_dir, dest_dir, ignore=ignore_patterns)
    return dest_dir


__all__ = [
    "save_to_volume",
    "copy_app_to_volume",
]
