"""Simplified Dagger workspace for klaudbiusz evaluation.

Adapted from agent/core/workspace.py with minimal dependencies.
"""

import logging
from typing import Self
import dagger
from dagger import Container, Directory
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    before_sleep_log,
)

from cli.utils.dagger_utils import ExecResult

logger = logging.getLogger(__name__)

retry_transport_errors = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=10),
    retry=retry_if_exception_type((dagger.TransportError, dagger.QueryError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)

# No retry for command execution errors (we want to see them immediately)
no_retry = retry(
    stop=stop_after_attempt(1),
)


class Workspace:
    """Dagger workspace for running containerized commands."""

    def __init__(self, ctr: Container, client: dagger.Client):
        self.ctr = ctr
        self._client = client

    @property
    def client(self) -> dagger.Client:
        """Get the Dagger client."""
        if self._client is None:
            raise RuntimeError("Client not initialized")
        return self._client

    @classmethod
    async def create(
        cls,
        client: dagger.Client,
        base_image: str = "alpine",
        context: Directory | None = None,
        setup_cmd: list[list[str]] = [],
    ) -> Self:
        """Create a new workspace with the given base image and context.

        Args:
            client: Dagger client
            base_image: Docker base image (e.g., "node:20-alpine")
            context: Optional directory to mount as /app
            setup_cmd: List of commands to run during setup

        Returns:
            Configured Workspace instance
        """
        my_context = context or client.directory()
        ctr = (
            client.container().from_(base_image).with_workdir("/app").with_directory("/app", my_context)
        )

        # Run setup commands (sync to force execution)
        for cmd in setup_cmd:
            ctr = ctr.with_exec(cmd)

        # Force execution of setup commands before returning
        if setup_cmd:
            ctr = await ctr.sync()

        return cls(ctr=ctr, client=client)

    @no_retry  # Don't retry command failures - we want immediate feedback
    async def exec(self, command: list[str], cwd: str = ".", update_ctr: bool = False) -> ExecResult:
        """Execute a command in the workspace.

        Args:
            command: Command to execute (as list of strings)
            cwd: Working directory (default: ".")
            update_ctr: If True, update self.ctr with the result container (for operations that modify filesystem)

        Returns:
            ExecResult with exit code, stdout, stderr
        """
        result_ctr = self.ctr.with_workdir(cwd).with_exec(command)
        if update_ctr:
            # Sync to force execution and capture filesystem changes
            self.ctr = await result_ctr.sync()
        return await ExecResult.from_ctr(result_ctr)

    def write_file(self, path: str, contents: str, force: bool = False) -> Self:
        """Write a file to the workspace.

        Args:
            path: File path
            contents: File contents
            force: Force write (ignore permissions, not used here)

        Returns:
            Self for chaining
        """
        self.ctr = self.ctr.with_new_file(path, contents)
        return self

    @retry_transport_errors
    async def read_file(self, path: str) -> str:
        """Read a file from the workspace.

        Args:
            path: File path

        Returns:
            File contents as string

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        try:
            return await self.ctr.file(path).contents()
        except dagger.QueryError:
            raise FileNotFoundError(f"File not found: {path}")
