import os
import tempfile
import dagger
from pathlib import Path
from typing import Self


class ExecResult:
    exit_code: int
    stdout: str
    stderr: str

    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    @classmethod
    async def from_ctr(cls, ctr: dagger.Container) -> Self:
        return cls(
            exit_code=await ctr.exit_code(),
            stdout=await ctr.stdout(),
            stderr=await ctr.stderr(),
        )


async def write_files_bulk(ctr: dagger.Container, files: dict[str, str], client: dagger.Client) -> dagger.Container:
    with tempfile.TemporaryDirectory() as temp_dir:
        for file_path, content in files.items():
            file = Path(os.path.join(temp_dir, file_path))
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        directory = client.host().directory(temp_dir)
        ctr = ctr.with_directory(".", directory)
        return await ctr.sync()
