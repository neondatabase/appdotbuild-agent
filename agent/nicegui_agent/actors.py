import re
import jinja2
import logging
import dataclasses
from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData, BaseActor, LLMActor
from llm.common import AsyncLLM, Message, TextRaw, Tool, ToolUse, ToolUseResult
from nicegui_agent import playbooks

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class File:
    path: str
    content: str


@dataclasses.dataclass
class FileDiff:
    path: str
    search: str
    replace: str


def extract_files(content: str) -> list[File | FileDiff]:
    file_pattern = re.compile(
        r"(?P<filename>\S+)\n```.*\n(?P<content>(?s:.*?))```",
    )
    replace_pattern = re.compile(
        r"<<<<<<< SEARCH.*\n(?P<search>(?s:.*?))=======.*\n(?P<replace>(?s:.*?))>>>>>>> REPLACE"
    )
    files = []
    for match in file_pattern.finditer(content):
        if diff := replace_pattern.search(match.group("content")):
            files.append(
                FileDiff(
                    match.group("filename").strip(),
                    diff.group("search").strip(),
                    diff.group("replace").strip(),
                )
            )
        else:
            files.append(
                File(
                    match.group("filename").strip(),
                    match.group("content").strip(),
                )
            )
    return files


async def run_write_files(node: Node[BaseData]) -> TextRaw | None:
    errors = []
    files_written = 0

    for block in node.data.head().content:
        if not (isinstance(block, TextRaw)):
            continue
        parsed_files = extract_files(block.text)
        if not parsed_files:
            continue
        num_diffs = sum(1 for item in parsed_files if isinstance(item, FileDiff))
        num_files = sum(1 for item in parsed_files if isinstance(item, File))
        logger.info(f"Writing {num_files} files, applying {num_diffs} diffs")
        for item in parsed_files:
            try:
                match item:
                    case File(path, content):
                        node.data.workspace.write_file(path, content)
                        node.data.files.update({path: content})
                        files_written += 1
                        logger.debug(f"Written file: {path}")
                    case FileDiff(path, search, replace):
                        try:
                            original = await node.data.workspace.read_file(path)
                        except FileNotFoundError as e:
                            raise ValueError(
                                f"Diff '{path}' not applied. Search:\n{search}"
                            ) from e
                        match original.count(search):
                            case 0:
                                raise ValueError(
                                    f"'{search}' not found in file '{path}'"
                                )
                            case 1:
                                new_content = original.replace(search, replace)
                                node.data.workspace.write_file(path, new_content)
                                node.data.files.update({path: new_content})
                                files_written += 1
                                logger.debug(f"Written diff block: {path}")
                            case num_hits:
                                raise ValueError(
                                    f"'{search}' found {num_hits} times in file '{path}'"
                                )
                    case unknown:
                        logger.error(f"Unknown file type: {unknown}")
            except ValueError as e:
                error_msg = str(e)
                logger.info(f"Error writing file {item.path}: {error_msg}")
                errors.append(error_msg)
            except FileNotFoundError as e:
                error_msg = str(e)
                logger.info(f"File not found error writing file {item.path}: {str(e)}")
                errors.append(error_msg)
            except PermissionError as e:
                error_msg = str(e)
                logger.info(f"Permission error writing file {item.path}: {error_msg}")
                errors.append(error_msg)

    if files_written > 0:
        logger.debug(f"Written {files_written} files to workspace")

    if errors:
        errors.append(
            f"Only those files should be written: {node.data.workspace.allowed}"
        )

    return TextRaw("\n".join(errors)) if errors else None


class NiceguiActor(BaseActor, LLMActor):
    root: Node[BaseData] | None = None

    def __init__(
        self,
        llm: AsyncLLM,
        workspace: Workspace,
        beam_width: int = 3,
        max_depth: int = 30,
    ):
        self.llm = llm
        self.workspace = workspace
        self.beam_width = beam_width
        self.max_depth = max_depth
        self.root = None
        logger.info(
            f"Initialized {self.__class__.__name__} with beam_width={beam_width}, max_depth={max_depth}"
        )

    async def execute(
        self,
        files: dict[str, str],
        user_prompt: str,
    ) -> Node[BaseData]:
        workspace = self.workspace.clone()
        logger.info(
            f"Start {self.__class__.__name__} execution with files: {files.keys()}"
        )
        for file_path, content in files.items():
            workspace.write_file(file_path, content)
        workspace.permissions(
            protected=self.files_protected, allowed=self.files_allowed
        )

        jinja_env = jinja2.Environment()
        user_prompt_template = jinja_env.from_string(playbooks.USER_PROMPT)
        repo_files = await self.get_repo_files(workspace, files)
        project_context = "\n".join(
            [
                "Project files:",
                *repo_files,
                "Writeable files and directories:",
                *self.files_allowed,
            ]
        )
        user_prompt_rendered = user_prompt_template.render(
            project_context=project_context,
            user_prompt=user_prompt,
        )
        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        self.root = Node(BaseData(workspace, [message], {}))

        solution: Node[BaseData] | None = None
        iteration = 0
        while solution is None:
            iteration += 1
            candidates = self.select(self.root)
            if not candidates:
                logger.info("No candidates to evaluate, search terminated")
                break

            logger.info(
                f"Iteration {iteration}: Running LLM on {len(candidates)} candidates"
            )
            nodes = await self.run_llm(
                candidates,
                system_prompt=playbooks.SYSTEM_PROMPT,
                tools=self.tools,
                max_tokens=8192,
            )
            logger.info(f"Received {len(nodes)} nodes from LLM")

            for i, new_node in enumerate(nodes):
                logger.info(f"Evaluating node {i + 1}/{len(nodes)}")
                if await self.eval_node(new_node, user_prompt):
                    logger.info(f"Found solution at depth {new_node.depth}")
                    solution = new_node
                    break
        if solution is None:
            logger.error(f"{self.__class__.__name__} failed to find a solution")
            raise ValueError("No solutions found")
        return solution

    def select(self, node: Node[BaseData]) -> list[Node[BaseData]]:
        if node.is_leaf:
            logger.info(f"Selecting root node {self.beam_width} times (beam search)")
            return [node] * self.beam_width

        def is_expandable(node: Node[BaseData]) -> bool:
            return node.is_leaf and node.depth <= self.max_depth

        candidates = [n for n in node.get_all_children() if is_expandable(n)]
        logger.debug(f"Selected {len(candidates)} leaf nodes for evaluation")
        return candidates

    @property
    def tools(self) -> list[Tool]:
        return [
            {
                "name": "read_file",
                "description": "Read file content",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "delete_file",
                "description": "Delete a file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "uv_add",
                "description": "Install packages",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "packages": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["packages"],
                },
            },
            {
                "name": "complete",
                "description": "Mark the task as complete. This will run tests and type checks to ensure the changes are correct.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    async def run_tools(
        self, node: Node[BaseData], user_prompt: str
    ) -> tuple[list[ToolUseResult], bool]:
        logger.info(f"Running tools for node {node._id}")
        result, is_completed = [], False
        for block in node.data.head().content:
            if not isinstance(block, ToolUse):
                continue
            try:
                logger.info(f"Running tool {block.name}")

                match block.name:
                    case "read_file":
                        tool_content = await node.data.workspace.read_file(
                            block.input["path"]
                        )  # pyright: ignore[reportIndexIssue]
                        result.append(ToolUseResult.from_tool_use(block, tool_content))
                    case "delete_file":
                        node.data.workspace.rm(block.input["path"])  # pyright: ignore[reportIndexIssue]
                        node.data.files.update({block.input["path"]: None})  # pyright: ignore[reportIndexIssue]
                        result.append(ToolUseResult.from_tool_use(block, "success"))
                    case "uv_add":
                        packages = block.input["packages"]  # pyright: ignore[reportIndexIssue]
                        exec_res = await node.data.workspace.exec_mut(
                            ["uv", "add", " ".join(packages)]
                        )
                        if exec_res.exit_code != 0:
                            result.append(
                                ToolUseResult.from_tool_use(
                                    block,
                                    f"Failed to add packages: {exec_res.stderr}",
                                    is_error=True,
                                )
                            )
                        else:
                            node.data.files.update(
                                {
                                    "pyproject.toml": await node.data.workspace.read_file(
                                        "pyproject.toml"
                                    )
                                }
                            )
                            result.append(ToolUseResult.from_tool_use(block, "success"))
                    case "complete":
                        if not self.has_modifications(node):
                            raise ValueError(
                                "Can not complete without writing any changes."
                            )
                        check_err = await self.run_checks(node, user_prompt)
                        if check_err:
                            logger.info(f"Failed to complete: {check_err}")
                        result.append(
                            ToolUseResult.from_tool_use(block, check_err or "success")
                        )
                        is_completed = check_err is None
                    case unknown:
                        raise ValueError(f"Unknown tool: {unknown}")
            except FileNotFoundError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except PermissionError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except ValueError as e:
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except Exception as e:
                logger.error(f"Unknown error: {e}")
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
        return result, is_completed

    async def eval_node(self, node: Node[BaseData], user_prompt: str) -> bool:
        files_errors = await run_write_files(node)
        tool_calls, is_completed = await self.run_tools(node, user_prompt)
        err_content = tool_calls + ([files_errors] if files_errors else [])
        if err_content:
            node.data.messages.append(Message(role="user", content=err_content))
        else:
            content = [TextRaw(text="Continue or mark completed.")]
            node.data.messages.append(Message(role="user", content=content))
        return is_completed

    def has_modifications(self, node: Node[BaseData]) -> bool:
        cur_node = node
        while cur_node is not None:
            if cur_node.data.files:
                return True
            cur_node = cur_node.parent
        return False

    async def run_checks(self, node: Node[BaseData], user_prompt: str) -> str | None:
        pytest_result = await node.data.workspace.exec(["uv", "run", "pytest"])
        if pytest_result.exit_code != 0:
            return f"{pytest_result.stdout}\n{pytest_result.stderr}"
        return None

    @property
    def files_allowed(self) -> list[str]:
        return ["app/", "tests/"]

    @property
    def files_protected(self) -> list[str]:
        return [
            "pyproject.toml",
            "main.py",
            "tests/conftest.py",
        ]

    async def get_repo_files(
        self, workspace: Workspace, files: dict[str, str]
    ) -> list[str]:
        repo_files = set(files.keys())
        repo_files.update(
            f"tests/{file_path}" for file_path in await workspace.ls("tests")
        )
        repo_files.update(f"app/{file_path}" for file_path in await workspace.ls("app"))
        # Include root-level files
        root_files = await workspace.ls(".")
        for file_path in root_files:
            if file_path in [
                "docker-compose.yml",
                "Dockerfile",
                "pyproject.toml",
                "main.py",
                "pytest.ini",
            ]:
                repo_files.add(file_path)
        return sorted(list(repo_files))

    async def dump(self) -> object:
        if self.root is None:
            return []
        return await self.dump_node(self.root)

    async def load(self, data: object):
        if not data:
            return
        if not isinstance(data, list):
            raise ValueError(f"Expected list got {type(data)}")
        self.root = await self.load_node(data)
