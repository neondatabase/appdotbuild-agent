import os
import anyio
import logging
from typing import Callable, Awaitable
from anyio.streams.memory import MemoryObjectSendStream
import jinja2
from trpc_agent import playbooks
from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData, BaseActor, LLMActor
from llm.common import AsyncLLM, Message, TextRaw, Tool, ToolUse, ToolUseResult, ContentBlock
from trpc_agent.playwright import PlaywrightRunner, drizzle_push
from core.workspace import ExecResult

from trpc_agent.utils import run_write_files, run_tsc_compile, run_frontend_build, run_tests

logger = logging.getLogger(__name__)


async def run_drizzle(node: Node[BaseData]) -> tuple[ExecResult, TextRaw | None]:
    logger.info("Running Drizzle database schema push")
    result = await drizzle_push(node.data.workspace.client, node.data.workspace.ctr, postgresdb=None)
    if result.exit_code == 0 and not result.stderr:
        logger.info("Drizzle schema push succeeded")
        return result, None

    logger.info(f"Drizzle schema push failed with exit code {result.exit_code}")
    return result, TextRaw(f"Error running drizzle: {result.stderr}")



class BaseTRPCActor(BaseActor, LLMActor):
    model_params: dict

    def __init__(self, llm: AsyncLLM, workspace: Workspace, model_params: dict, beam_width: int = 5, max_depth: int = 5, event_callback: Callable[[dict[str, str]], Awaitable[None]] | None = None):
        self.llm = llm
        self.workspace = workspace
        self.model_params = model_params
        self.beam_width = beam_width
        self.max_depth = max_depth
        self.event_callback = event_callback
        logger.info(f"Initialized {self.__class__.__name__} with beam_width={beam_width}, max_depth={max_depth}")

    async def search(self, node: Node[BaseData] | None) -> Node[BaseData] | None:
        if node is None:
            raise RuntimeError("Node cannot be None")
        logger.info(f"Starting search from node at depth {node.depth}")
        solution: Node[BaseData] | None = None
        iteration = 0

        while solution is None:
            iteration += 1
            candidates = self.select(node)
            if not candidates:
                logger.info("No candidates to evaluate, search terminated")
                break

            logger.info(f"Iteration {iteration}: Running LLM on {len(candidates)} candidates")
            nodes = await self.run_llm(candidates, **self.model_params)
            logger.info(f"Received {len(nodes)} nodes from LLM")

            for i, new_node in enumerate(nodes):
                logger.info(f"Evaluating node {i+1}/{len(nodes)}")
                if await self.eval_node(new_node):
                    logger.info(f"Found solution at depth {new_node.depth}")
                    solution = new_node
                    break

        return solution

    def select(self, node: Node[BaseData]) -> list[Node[BaseData]]:
        if node.is_leaf:
            logger.info(f"Selecting root node {self.beam_width} times (beam search)")
            return [node] * self.beam_width

        candidates = [n for n in node.get_all_children() if n.is_leaf and n.depth <= self.max_depth]
        logger.info(f"Selected {len(candidates)} leaf nodes for evaluation")
        return candidates

    async def eval_node(self, node: Node[BaseData]) -> bool:
        ...


class DraftActor(BaseTRPCActor):
    root: Node[BaseData] | None = None

    def __init__(self, llm: AsyncLLM, workspace: Workspace, model_params: dict, beam_width: int = 1, max_depth: int = 5, event_callback: Callable[[dict[str, str]], Awaitable[None]] | None = None):
        super().__init__(llm, workspace, model_params, beam_width=beam_width, max_depth=max_depth, event_callback=event_callback)
        self.root = None

    async def execute(self, user_prompt: str) -> Node[BaseData]:
        logger.info(f"Executing DraftActor with user prompt: '{user_prompt}'")
        await self.cmd_create(user_prompt)
        solution = await self.search(self.root)
        if solution is None:
            logger.error("Draft actor failed to find a solution")
            raise ValueError("No solution found")
        logger.info("Draft actor completed successfully")
        return solution

    async def cmd_create(self, user_prompt: str):
        logger.info("Creating initial draft node")
        workspace = self.workspace.clone().permissions(allowed=self.files_allowed)
        context = []

        # Collect relevant files for context
        logger.info(f"Collecting {len(self.files_relevant)} relevant files for context")

        for path in self.files_relevant:
            content = await workspace.read_file(path)
            context.append(f"\n<file path=\"{path}\">\n{content.strip()}\n</file>\n")
            logger.debug(f"Added {path} to context")

        context.extend([
            "APP_DATABASE_URL=postgres://postgres:postgres@postgres:5432/postgres",
            f"Allowed paths and directories: {self.files_allowed}",
        ])

        # Prepare prompt for LLM
        logger.info("Preparing prompt template for LLM")
        jinja_env = jinja2.Environment()
        user_prompt_template = jinja_env.from_string(playbooks.BACKEND_DRAFT_USER_PROMPT)
        user_prompt_rendered = user_prompt_template.render(
            project_context="\n".join(context),
            user_prompt=user_prompt,
        )

        # Store system prompt separately
        self.model_params["system_prompt"] = playbooks.BACKEND_DRAFT_SYSTEM_PROMPT

        # Create root node
        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        self.root = Node(BaseData(workspace, [message], {}))
        logger.info("Created root node for draft")

    async def eval_node(self, node: Node[BaseData]) -> bool:
        logger.info("Evaluating draft node")

        # Process and write files
        files_err = await run_write_files(node, self.event_callback)
        if files_err:
            logger.info("File writing errors detected")
            node.data.messages.append(Message(role="user", content=[files_err]))
            return False

        # TypeScript compilation check
        _, tsc_err = await run_tsc_compile(node)
        if tsc_err:
            logger.info("TypeScript compilation errors detected")
            node.data.messages.append(Message(role="user", content=[tsc_err]))
            return False

        # Drizzle schema validation check
        _, drizzle_err = await run_drizzle(node)
        if drizzle_err:
            logger.info("Drizzle schema errors detected")
            node.data.messages.append(Message(role="user", content=[drizzle_err]))
            return False

        logger.info("Node evaluation succeeded")
        return True

    @property
    def files_relevant(self) -> list[str]:
        return ["server/src/db/index.ts", "server/package.json"]

    @property
    def files_allowed(self) -> list[str]:
        return ["server/src/schema.ts", "server/src/db/schema.ts", "server/src/handlers/", "server/src/index.ts"]

    async def dump(self) -> object:
        if self.root is None:
            return []
        return await self.dump_node(self.root)

    async def load(self, data: object):
        if not isinstance(data, list):
            raise ValueError(f"Expected list got {type(data)}")
        if not data:
            return
        self.root = await self.load_node(data)


class HandlersActor(BaseTRPCActor):
    handlers: dict[str, Node[BaseData]]

    def __init__(self, llm: AsyncLLM, workspace: Workspace, model_params: dict, beam_width: int = 1, max_depth: int = 5, event_callback: Callable[[dict[str, str]], Awaitable[None]] | None = None):
        super().__init__(llm, workspace, model_params, beam_width=beam_width, max_depth=max_depth, event_callback=event_callback)
        self.handlers = {}

    async def execute(self, files: dict[str, str], feedback_data: str | None) -> dict[str, Node[BaseData]]:
        logger.info(f"Executing HandlersActor with {len(files)} input files")

        async def task_fn(node: Node[BaseData], key: str, tx: MemoryObjectSendStream[tuple[str, Node[BaseData] | None]]):
            logger.info(f"Starting search for handler: {key}")
            result = await self.search(node)
            logger.info(f"Completed search for handler: {key}")
            async with tx:
                await tx.send((key, result))

        await self.cmd_create(files, feedback_data)

        logger.info(f"Starting parallel processing of {len(self.handlers)} handlers")
        solution: dict[str, Node[BaseData]] = {}
        tx, rx = anyio.create_memory_object_stream[tuple[str, Node[BaseData] | None]]()

        async with anyio.create_task_group() as tg:
            for name, node in self.handlers.items():
                logger.info(f"Scheduling task for handler: {name}")
                tg.start_soon(task_fn, node, name, tx.clone())
            tx.close()

            async with rx:
                async for (key, node) in rx:
                    if not node:
                        # FixMe: should we expose this to top level?
                        logger.warning(f"Handler {key} returned no solution or an empty node, skipping")
                    else:
                        solution[key] = node
                        logger.info(f"Received solution for handler: {key}")

        logger.info(f"HandlersActor completed with {len(solution)} solutions")
        return solution

    async def cmd_create(self, files: dict[str, str], feedback_data: str | None):
        logger.info("Creating handler nodes")
        self.handlers = {}

        # Set up workspace with inherited files
        workspace = self.workspace.clone()
        for file in self.files_inherit:
            if file in files:
                workspace.write_file(file, files[file])
                logger.debug(f"Copied inherited file: {file}")

        # Prepare jinja template
        jinja_env = jinja2.Environment()
        user_prompt_template = jinja_env.from_string(playbooks.BACKEND_HANDLER_USER_PROMPT)

        # Process handler files
        handler_count = 0
        for file, content in files.items():
            if not file.startswith("server/src/handlers/") or not file.endswith(".ts"):
                continue

            handler_name, _ = os.path.splitext(os.path.basename(file))
            logger.info(f"Processing handler: {handler_name}")

            # Create workspace with permissions
            allowed = [file, f"server/src/tests/{handler_name}.test.ts"]
            handler_ws = workspace.clone().permissions(allowed=allowed).write_file(file, content)

            # Build context with relevant files
            context = []
            for path in self.files_relevant + [file]:
                file_content = await handler_ws.read_file(path)
                context.append(f"\n<file path=\"{path}\">\n{file_content.strip()}\n</file>\n")

            context.append(f"Allowed paths and directories: {allowed}")

            # Render user prompt and create node
            user_prompt_rendered = user_prompt_template.render(
                project_context="\n".join(context),
                handler_name=handler_name,
                feedback_data=feedback_data,
            )

            # Store system prompt separately in model_params
            self.model_params["system_prompt"] = playbooks.BACKEND_HANDLER_SYSTEM_PROMPT

            message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
            node = Node(BaseData(handler_ws, [message], {}))
            self.handlers[handler_name] = node
            handler_count += 1

        logger.info(f"Created {handler_count} handler nodes")

    async def eval_node(self, node):
        logger.info("Evaluating handler node")

        # Process and write files
        files_err = await run_write_files(node, self.event_callback)
        if files_err:
            logger.info("File writing errors detected")
            node.data.messages.append(Message(role="user", content=[files_err]))
            return False

        # TypeScript compilation check
        _, tsc_err = await run_tsc_compile(node)
        if tsc_err:
            logger.info("TypeScript compilation errors detected")
            node.data.messages.append(Message(role="user", content=[tsc_err]))
            return False

        # Run tests
        _, test_err = await run_tests(node)
        if test_err:
            logger.info("Test failures detected")
            node.data.messages.append(Message(role="user", content=[test_err]))
            return False

        logger.info("Handler node evaluation succeeded")
        return True

    @property
    def files_inherit(self) -> list[str]:
        return ["server/src/db/schema.ts", "server/src/schema.ts"]

    @property
    def files_relevant(self) -> list[str]:
        return ["server/src/helpers/index.ts", "server/src/schema.ts", "server/src/db/schema.ts"]

    async def dump(self) -> object:
        if not self.handlers:
            return {}
        return {name: await self.dump_node(node) for name, node in self.handlers.items()}

    async def load(self, data: object):
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict got {type(data)}")
        self.handlers = {}
        for name, node_data in data.items():
            node = await self.load_node(node_data)
            self.handlers[name] = node


class FrontendActor(BaseTRPCActor):
    root: Node[BaseData] | None = None

    def __init__(self, llm: AsyncLLM, vlm: AsyncLLM, workspace: Workspace, model_params: dict, beam_width: int = 1, max_depth: int = 5, event_callback: Callable[[dict[str, str]], Awaitable[None]] | None = None):
        super().__init__(llm, workspace, {**model_params, "tools": self.tools}, beam_width=beam_width, max_depth=max_depth, event_callback=event_callback)
        self.root = None
        self.playwright_runner = PlaywrightRunner(vlm=vlm)
        self._user_prompt = None

    async def execute(self, user_prompt: str, server_files: dict[str, str]) -> Node[BaseData]:
        logger.info(f"Executing frontend actor with user prompt: {user_prompt}")
        self._user_prompt = user_prompt
        await self.cmd_create(user_prompt, server_files)
        solution = await self.search(self.root)
        if solution is None:
            raise ValueError("No solution found")
        return solution

    async def cmd_create(self, user_prompt: str, server_files: dict[str, str]):
        workspace = self.workspace.clone()
        for file, content in server_files.items():
            workspace.write_file(file, content)
        workspace = workspace.permissions(protected=self.files_protected, allowed=self.files_allowed)
        context = []
        for path in self.files_relevant:
            content = await workspace.read_file(path)
            context.append(f"\n<file path=\"{path}\">\n{content.strip()}\n</file>\n")
        ui_files = await self.workspace.ls("client/src/components/ui")
        context.extend([
            f"UI components in client/src/components/ui: {ui_files}",
            f"Allowed paths and directories: {self.files_allowed}",
            f"Protected paths and directories: {self.files_protected}",
        ])
        jinja_env = jinja2.Environment()
        user_prompt_template = jinja_env.from_string(playbooks.FRONTEND_USER_PROMPT)
        user_prompt_rendered = user_prompt_template.render(
            project_context="\n".join(context),
            user_prompt=user_prompt,
        )
        self.model_params["system_prompt"] = playbooks.FRONTEND_SYSTEM_PROMPT

        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        self.root = Node(BaseData(workspace, [message], {}))


    async def eval_node(self, node: Node[BaseData]) -> bool:
        content: list[ContentBlock] = []
        content.extend(await self.run_tools(node))
        files_err = await run_write_files(node, self.event_callback)
        if files_err:
            content.append(files_err)
        if node.data.files:
            tsc_result = await node.data.workspace.exec(["bun", "run", "tsc", "-p", "tsconfig.app.json", "--noEmit"], cwd="client")
            if tsc_result.exit_code != 0:
                content.append(TextRaw(f"Error running tsc: {tsc_result.stdout}"))
        if content:
            node.data.messages.append(Message(role="user", content=content))
            return False

        build_err = await run_frontend_build(node)
        if build_err:
            content.append(TextRaw(build_err))
            node.data.messages.append(Message(role="user", content=content))
            return False

        playwright_feedback = await self.playwright_runner.evaluate(node, self._user_prompt or "", mode="client")
        if playwright_feedback:
            content += [TextRaw(x) for x in playwright_feedback]
            node.data.messages.append(Message(role="user", content=content))
            return False

        return True

    async def run_tools(self, node: Node[BaseData]) -> list[ToolUseResult]:
        result = []
        for block in node.data.head().content:
            if not isinstance(block, ToolUse):
                continue
            match block.name:
                case "read_file":
                    try:
                        tool_content = await node.data.workspace.read_file(block.input["path"]) # pyright: ignore[reportIndexIssue]
                        result.append(ToolUseResult.from_tool_use(block, tool_content))
                    except FileNotFoundError as e:
                        result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
                case unknown:
                    result.append(ToolUseResult.from_tool_use(block, f"Unknown tool: {unknown}", is_error=True))
        return result

    @property
    def files_relevant(self) -> list[str]:
        return ["server/src/schema.ts", "server/src/index.ts", "client/src/utils/trpc.ts"]

    @property
    def files_protected(self) -> list[str]:
        return ["client/src/components/ui/"]

    @property
    def files_allowed(self) -> list[str]:
        return ["client/src/App.tsx", "client/src/components/", "client/src/App.css"]

    @property
    def tools(self) -> list[Tool]:
        return [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                }
            },
        ]

    async def dump(self) -> object:
        if self.root is None:
            node = []
        else:
            node = await self.dump_node(self.root)
        return {
            "node": node,
            "user_prompt": self._user_prompt,
        }

    async def load(self, data: object):
        match data:
            case dict():
                node = data.get("node")
                if not node:
                    return
                if not isinstance(node, list):
                    raise ValueError(f"Expected list got {type(node)}")
                self.root = await self.load_node(node)
                self._user_prompt = data.get("user_prompt")
            case _:
                raise ValueError(f"Expected dict got {type(data)}")


class ConcurrentActor(BaseTRPCActor):
    handlers: HandlersActor
    frontend: FrontendActor

    def __init__(self, handlers: HandlersActor, frontend: FrontendActor):
        self.handlers = handlers
        self.frontend = frontend

    async def execute(self, user_prompt: str, server_files: dict[str, str], feedback_data: str | None) -> dict[str, Node[BaseData]]:
        result: dict[str, Node[BaseData]] = {}
        async def solve_frontend():
            result["frontend"] = await self.frontend.execute(feedback_data or user_prompt, server_files)
        async def solve_handlers():
            handlers_solution = await self.handlers.execute(server_files, feedback_data)
            result.update(handlers_solution)
        async with anyio.create_task_group() as tg:
            tg.start_soon(solve_frontend)
            tg.start_soon(solve_handlers)
        return result

    async def dump(self) -> object:
        return {
            "frontend": await self.frontend.dump(),
            "handlers": await self.handlers.dump(),
        }

    async def load(self, data: object):
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict got {type(data)}")
        if not data:
            return
        await self.handlers.load(data["handlers"])
        await self.frontend.load(data["frontend"])
