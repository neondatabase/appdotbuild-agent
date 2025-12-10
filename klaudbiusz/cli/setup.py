"""
Self-setup CLI command for klaudbiusz.

Enables easy installation in CI/CD or Databricks environments:
    python -m cli.setup --clone-to /tmp/klaudbiusz --install-deps
    python -m cli.setup --install-deps
"""

import os
import subprocess
import sys
from pathlib import Path

import fire


def main(
    clone_to: str | None = None,
    install_deps: bool = True,
    git_url: str = "https://github.com/appdotbuild/agent.git",
    branch: str = "main",
) -> None:
    """Self-setup klaudbiusz in a new environment.

    Args:
        clone_to: Directory to clone the repository to (optional).
                  If provided, clones the repo and changes to klaudbiusz subdir.
        install_deps: Whether to install dependencies via pip (default: True).
        git_url: Git repository URL to clone from.
        branch: Git branch to checkout (default: main).

    Examples:
        # Clone and install in one command
        python -m cli.setup --clone-to /tmp/klaudbiusz --install-deps

        # If already cloned, just install deps
        python -m cli.setup --install-deps

        # Clone specific branch
        python -m cli.setup --clone-to /tmp/klaudbiusz --branch feature-branch
    """
    if clone_to:
        clone_path = Path(clone_to)
        if clone_path.exists():
            print(f"Directory already exists: {clone_path}")
            print("Remove it first or use a different path.")
            sys.exit(1)

        print(f"Cloning {git_url} to {clone_path}...")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, git_url, str(clone_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"Git clone failed: {result.stderr}")
            sys.exit(1)

        klaudbiusz_path = clone_path / "klaudbiusz"
        if not klaudbiusz_path.exists():
            print(f"klaudbiusz directory not found in {clone_path}")
            sys.exit(1)

        os.chdir(klaudbiusz_path)
        print(f"Changed to: {klaudbiusz_path}")

    if install_deps:
        print("Installing dependencies...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"pip install failed: {result.stderr}")
            sys.exit(1)
        print("Dependencies installed successfully.")

    print("Setup complete!")


if __name__ == "__main__":
    fire.Fire(main)
