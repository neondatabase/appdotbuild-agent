import re
import jinja2
import logging
import dataclasses
from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData, BaseActor, LLMActor
from llm.common import AsyncLLM, Message, TextRaw, Tool, ToolUse, ToolUseResult
from trpc_agent import playbooks
from trpc_agent.actors import run_tests, run_tsc_compile, run_frontend_build
from trpc_agent.playwright import PlaywrightRunner
from trpc_agent.notification_utils import notify_if_callback, notify_files_processed

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
        if (diff := replace_pattern.search(match.group("content"))):
            files.append(FileDiff(
                match.group("filename").strip(),
                diff.group("search").strip(),
                diff.group("replace").strip(),
            ))
        else:
            files.append(File(
                match.group("filename").strip(),
                match.group("content").strip(),
            ))
    return files


async def run_write_files(node: Node[BaseData], event_callback = None) -> TextRaw | None:
    errors = []
    files_written = 0
    all_files_written = []

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
                        all_files_written.append(path)
                        logger.debug(f"Written file: {path}")
                    case FileDiff(path, search, replace):
                        try:
                            original = await node.data.workspace.read_file(path)
                        except FileNotFoundError as e:
                            raise ValueError(f"Diff '{path}' not applied. Search:\n{search}") from e
                        match original.count(search):
                            case 0:
                                raise ValueError(f"'{search}' not found in file '{path}'")
                            case 1:
                                new_content = original.replace(search, replace)
                                node.data.workspace.write_file(path, new_content)
                                node.data.files.update({path: new_content})
                                files_written += 1
                                all_files_written.append(path)
                                logger.debug(f"Written diff block: {path}")
                            case num_hits:
                                raise ValueError(f"'{search}' found {num_hits} times in file '{path}'")
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
        # Calculate edit vs new file counts
        edit_count = sum(1 for item in parsed_files if isinstance(item, FileDiff))
        new_count = sum(1 for item in parsed_files if isinstance(item, File))
        
        await notify_files_processed(
            event_callback, 
            all_files_written, 
            edit_count=edit_count, 
            new_count=new_count, 
            operation_type="edit"
        )

    if errors:
        errors.append(f"Only those files should be written: {node.data.workspace.allowed}")

    return TextRaw("\n".join(errors)) if errors else None


class EditActor(BaseActor, LLMActor):
    root: Node[BaseData] | None = None

    def __init__(
        self,
        llm: AsyncLLM,
        vlm: AsyncLLM,
        workspace: Workspace,
        beam_width: int = 3,
        max_depth: int = 30,
        event_callback = None,
    ):
        self.llm = llm
        self.workspace = workspace
        self.beam_width = beam_width
        self.max_depth = max_depth
        self.root = None
        self.playwright = PlaywrightRunner(vlm)
        self.event_callback = event_callback
        logger.info(f"Initialized {self.__class__.__name__} with beam_width={beam_width}, max_depth={max_depth}")

    async def execute(
        self,
        files: dict[str, str],
        user_prompt: str,
        feedback: str,
    ) -> Node[BaseData]:
        await notify_if_callback(self.event_callback, "🛠️ Applying requested changes...", "edit start")
        
        workspace = self.workspace.clone()
        logger.info(f"Start EditActor execution with files: {files.keys()}")
        for file_path, content in files.items():
            workspace.write_file(file_path, content)
        workspace.permissions(protected=self.files_protected, allowed=self.files_allowed)

        jinja_env = jinja2.Environment()
        user_prompt_template = jinja_env.from_string(playbooks.EDIT_ACTOR_USER_PROMPT)
        repo_files = await self.get_repo_files(workspace, files)
        project_context = "\n".join([
            "Project files:",
            *repo_files,
            "Writeable files and directories:",
            *self.files_allowed,
            "Protected files and directories:",
            *self.files_protected
        ])
        user_prompt_rendered = user_prompt_template.render(
            project_context=project_context,
            user_prompt=user_prompt,
            feedback=feedback
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

            await notify_if_callback(self.event_callback, f"🔄 Working on changes (iteration {iteration})...", "iteration progress")

            logger.info(f"Iteration {iteration}: Running LLM on {len(candidates)} candidates")
            nodes = await self.run_llm(
                candidates,
                system_prompt=playbooks.EDIT_ACTOR_SYSTEM_PROMPT,
                tools=self.tools,
                max_tokens=8192,
            )
            logger.info(f"Received {len(nodes)} nodes from LLM")

            for i, new_node in enumerate(nodes):
                logger.info(f"Evaluating node {i+1}/{len(nodes)}")
                if await self.eval_node(new_node, user_prompt):
                    logger.info(f"Found solution at depth {new_node.depth}")
                    await notify_if_callback(self.event_callback, "✅ Changes applied successfully!", "edit completion")
                    solution = new_node
                    break
        if solution is None:
            logger.error("EditActor failed to find a solution")
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
                }
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
                }
            },
            {
                "name": "complete",
                "description": "Mark the task as complete. This will run tests and type checks to ensure the changes are correct.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                }
            }
        ]

    async def run_tools(self, node: Node[BaseData], user_prompt: str) -> tuple[list[ToolUseResult], bool]:
        logger.info(f"Running tools for node {node._id}")
        result, is_completed = [], False
        for block in node.data.head().content:
            if not isinstance(block, ToolUse):
                continue
            try:
                logger.info(f"Running tool {block.name}")

                match block.name:
                    case "read_file":
                        tool_content = await node.data.workspace.read_file(block.input["path"]) # pyright: ignore[reportIndexIssue]
                        result.append(ToolUseResult.from_tool_use(block, tool_content))
                    case "delete_file":
                        node.data.workspace.rm(block.input["path"]) # pyright: ignore[reportIndexIssue]
                        node.data.files.update({block.input["path"]: None}) # pyright: ignore[reportIndexIssue]
                        result.append(ToolUseResult.from_tool_use(block, "success"))
                    case "complete":
                        if not self.has_modifications(node):
                            raise ValueError("Can not complete without writing any changes.")
                        check_err = await self.run_checks(node, user_prompt)
                        result.append(ToolUseResult.from_tool_use(block, check_err or "success"))
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
        files_errors = await run_write_files(node, self.event_callback)
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
        await notify_if_callback(self.event_callback, "🔍 Validating changes...", "validation start")

        _, tsc_compile_err = await run_tsc_compile(node, self.event_callback)
        if tsc_compile_err:
            return f"TypeScript compile errors (backend):\n{tsc_compile_err.text}\n"

        # client tsc compile - should be refactored for the consistency
        await notify_if_callback(self.event_callback, "🔧 Compiling frontend TypeScript...", "frontend compile start")
        
        tsc_result = await node.data.workspace.exec(["bun", "run", "tsc", "-p", "tsconfig.app.json", "--noEmit"], cwd="client")
        if tsc_result.exit_code != 0:
            await notify_if_callback(self.event_callback, "❌ Frontend TypeScript compilation failed", "frontend compile failure")
            return f"TypeScript compile errors (frontend): {tsc_result.stdout}"

        _, test_result = await run_tests(node, self.event_callback)
        if test_result:
            return f"Test errors:\n{test_result.text}\n"

        build_result = await run_frontend_build(node, self.event_callback)
        if build_result:
            return build_result

        await notify_if_callback(self.event_callback, "🎭 Running UI validation...", "playwright start")

        playwright_result = await self.playwright.evaluate(node, user_prompt, mode="full")
        if playwright_result:
            await notify_if_callback(self.event_callback, "❌ UI validation failed - adjusting...", "playwright failure")
            return "\n".join(playwright_result)
        
        await notify_if_callback(self.event_callback, "✅ All validations passed!", "validation success")
        
        return None

    @property
    def files_allowed(self) -> list[str]:
        return [
            "server/src/schema.ts",
            "server/src/db/schema.ts",
            "server/src/handlers/",
            "server/src/tests/",
            "server/src/index.ts",
            "client/src/App.tsx",
            "client/src/components/",
            "client/src/App.css",
        ]

    @property
    def files_protected(self) -> list[str]:
        return [
            "Dockerfile",
            "server/src/db/index.ts",
            "client/src/utils/trpc.ts",
            "client/src/components/ui/",
        ]

    @property
    def files_visible(self) -> list[str]:
        return [
            "client/src/components/ui/",
        ]

    async def get_repo_files(self, workspace: Workspace, files: dict[str, str]) -> list[str]:
        repo_files = set([
            "server/src/schema.ts",
            "server/src/db/index.ts",
            "server/src/db/schema.ts",
            "server/src/index.ts",
            "server/src/package.json",
            "client/src/App.tsx",
            "client/src/App.css",
            "client/src/utils/trpc.ts",
            "client/src/lib/utils.ts",
            "client/src/package.json",
        ])
        repo_files.update(files.keys())
        repo_files.update(await workspace.ls("client/src/components/ui"))
        return list(repo_files)

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
