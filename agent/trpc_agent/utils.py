import re
import logging
from typing import Callable, Awaitable
from core.base_node import Node
from core.workspace import ExecResult
from core.actors import BaseData
from llm.common import TextRaw

logger = logging.getLogger(__name__)


class ParseFiles:
    def __init__(self):
        self.pattern = re.compile(
            r'<file path="(?P<path>[^"]+)">(?P<content>.*?)</file>',
            re.DOTALL
        )

    def __call__(self, content: str):
        matches = self.pattern.finditer(content)
        return {match.group("path"): match.group("content") for match in matches}


parse_files = ParseFiles()


async def run_write_files(
    node: Node[BaseData],
    event_callback: Callable[[str], Awaitable[None]] | None = None,
) -> TextRaw | None:
    errors = []
    files_written = 0

    for block in node.data.head().content:
        if not (isinstance(block, TextRaw)):
            continue
        parsed_files = parse_files(block.text)
        for file, content in parsed_files.items():
            try:
                node.data.workspace.write_file(file, content)
                node.data.files.update({file: content})
                files_written += 1
                logger.debug(f"Written file: {file}")
            except PermissionError as e:
                error_msg = str(e)
                logger.info(f"Permission error writing file {file}: {error_msg}")
                errors.append(error_msg)

    if files_written > 0:
        logger.debug(f"Written {files_written} files to workspace")
        if event_callback:
            try:
                diff_output = await node.data.workspace.diff(node.data.files)
                await event_callback(diff_output)
            except Exception as e:
                logger.warning(f"Failed to emit intermediate files: {e}")

    if errors:
        errors.append(f"Only those files should be written: {node.data.workspace.allowed}")

    return TextRaw("\n".join(errors)) if errors else None


async def run_tsc_compile(node: Node[BaseData]) -> tuple[ExecResult, TextRaw | None]:
    logger.debug("Running TypeScript compilation")
    result = await node.data.workspace.exec(["bun", "run", "tsc", "--noEmit", "--incremental"], cwd="server")
    if result.exit_code == 0:
        logger.info("TypeScript compilation succeeded")
        return result, None

    logger.debug(f"TypeScript compilation failed with exit code {result.exit_code}")
    return result, TextRaw(f"Error running tsc: {result.stdout}")




class RunTests:
    def __init__(self):
        self.test_output_normalizer = re.compile(r"\[\d+(\.\d+)?(ms|s)\]")

    async def __call__(self, node: Node[BaseData]) -> tuple[ExecResult, TextRaw | None]:
        result = await node.data.workspace.exec_with_pg(["bun", "test"], cwd="server")
        if result.exit_code == 0:
            return result, None

        logger.info(f"Tests failed with exit code {result.exit_code}")
        err = self.test_output_normalizer.sub("", result.stderr)
        err = "\n".join([x.rstrip() for x in err.splitlines()])
        return result, TextRaw(f"Error running tests: {err}")

run_tests = RunTests()

class RunFrontendBuild:
    def __init__(self):
        self.build_output_normalizer = re.compile(r"\d+(\.\d+)?(ms|s)")

    async def __call__(self, node: Node[BaseData]) -> str | None:
        result = await node.data.workspace.exec(["bun", "run", "build"], cwd="client")
        if result.exit_code != 0:
            err = self.build_output_normalizer.sub("", result.stderr)
            return f"Build errors:\n{err}\n"

        result = await node.data.workspace.exec(["bun", "run", "lint"], cwd="client")
        if result.exit_code != 0:
            logger.info(f"Linting failed with exit code {result.exit_code}")
            return f"Lint errors:\n{result.stdout}\n"

        return None

run_frontend_build = RunFrontendBuild()
