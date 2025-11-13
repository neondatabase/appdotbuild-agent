"""Simplified Dagger utilities for klaudbiusz evaluation."""

import dagger
from typing import Self


class ExecResult:
    """Result of executing a command in a Dagger container."""

    exit_code: int
    stdout: str
    stderr: str

    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    @classmethod
    async def from_ctr(cls, ctr: dagger.Container) -> Self:
        """Create ExecResult from a Dagger container."""
        return cls(
            exit_code=await ctr.exit_code(),
            stdout=await ctr.stdout(),
            stderr=await ctr.stderr(),
        )
