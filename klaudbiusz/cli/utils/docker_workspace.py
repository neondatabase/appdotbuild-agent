"""Docker-based workspace using docker CLI instead of Dagger.

Provides the same interface as Workspace but uses subprocess calls to docker CLI.
Useful for environments that have Docker but not Dagger (e.g., Databricks Jobs).
"""

import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Self

from cli.utils.dagger_utils import ExecResult

logger = logging.getLogger(__name__)


class DockerWorkspace:
    """Docker-based workspace using docker CLI instead of Dagger."""

    def __init__(self, container_id: str, container_name: str, workdir: str = "/app"):
        self.container_id = container_id
        self.container_name = container_name
        self.workdir = workdir

    @classmethod
    def create(
        cls,
        app_dir: Path,
        base_image: str = "node:20-alpine",
        port: int = 8000,
        env_vars: dict[str, str] | None = None,
    ) -> Self:
        """Create and start a Docker container for evaluation.

        Args:
            app_dir: Path to the app directory on host
            base_image: Docker base image (default: node:20-alpine)
            port: Port to expose for the app
            env_vars: Environment variables to set in container

        Returns:
            DockerWorkspace instance with running container
        """
        # Generate unique container name
        container_name = f"eval-{app_dir.name}-{port}-{uuid.uuid4().hex[:8]}"

        # Build docker run command
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "-v", f"{app_dir.resolve()}:/app",
            "-w", "/app",
        ]

        # Add environment variables
        env_vars = env_vars or {}
        for key, value in env_vars.items():
            if value:  # Only add non-empty values
                cmd.extend(["-e", f"{key}={value}"])

        # Add image and keep-alive command
        cmd.extend([
            base_image,
            "tail", "-f", "/dev/null"  # Keep container running
        ])

        logger.debug(f"Starting container: {' '.join(cmd)}")

        # Start container
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")

        container_id = result.stdout.strip()
        workspace = cls(container_id, container_name, workdir="/app")

        # Run setup commands (install bash and curl)
        setup_result = workspace.exec(["apk", "add", "--no-cache", "bash", "curl"])
        if setup_result.exit_code != 0:
            workspace.cleanup()
            raise RuntimeError(f"Failed to install dependencies: {setup_result.stderr}")

        return workspace

    def exec(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: int = 300,
    ) -> ExecResult:
        """Execute command in container using docker exec.

        Args:
            command: Command to execute (as list of strings)
            cwd: Working directory (default: container workdir)
            timeout: Timeout in seconds

        Returns:
            ExecResult with exit code, stdout, stderr
        """
        workdir = cwd or self.workdir

        docker_cmd = [
            "docker", "exec",
            "-w", workdir,
            self.container_id,
        ] + command

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ExecResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                exit_code=124,  # Standard timeout exit code
                stdout="",
                stderr=f"Command timed out after {timeout}s",
            )

    def write_file(self, path: str, contents: str) -> Self:
        """Write a file to the container.

        Args:
            path: File path in container
            contents: File contents

        Returns:
            Self for chaining
        """
        # Use docker exec with bash to write file
        # Escape single quotes in contents
        escaped = contents.replace("'", "'\"'\"'")
        cmd = ["docker", "exec", self.container_id, "bash", "-c", f"cat > '{path}' << 'EOFMARKER'\n{contents}\nEOFMARKER"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning(f"Failed to write file {path}: {result.stderr}")

        return self

    def copy_file(self, src: Path, dest: str) -> Self:
        """Copy a file from host to container.

        Args:
            src: Source path on host
            dest: Destination path in container

        Returns:
            Self for chaining
        """
        cmd = ["docker", "cp", str(src), f"{self.container_id}:{dest}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning(f"Failed to copy file {src} to {dest}: {result.stderr}")

        return self

    def cleanup(self) -> None:
        """Stop and remove the container."""
        try:
            subprocess.run(
                ["docker", "rm", "-f", self.container_id],
                capture_output=True,
                timeout=30,
            )
            logger.debug(f"Removed container {self.container_name}")
        except Exception as e:
            logger.warning(f"Failed to remove container {self.container_name}: {e}")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()
