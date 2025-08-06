from typing import Protocol
import dataclasses
import anyio
from anyio.streams.memory import MemoryObjectSendStream
from core import statemachine
from core.base_node import Node
from llm.common import AsyncLLM, Message, InternalMessage
from llm.utils import loop_completion, extract_tag
from core.workspace import Workspace
import hashlib
from abc import ABC, abstractmethod
from llm.common import Tool, ToolUse, ToolUseResult, TextRaw
from llm.utils import get_ultra_fast_llm_client
from log import get_logger

logger = get_logger(__name__)


class AgentSearchFailedException(Exception):
    """Exception raised when an agent's search process fails to find candidates."""
    def __init__(self, agent_name: str, message: str = "No candidates to evaluate, search terminated"):
        self.agent_name = agent_name
        self.message = message
        # Create a more user-friendly message
        user_message = f"The {agent_name} encountered an issue: {message}. This typically happens when the agent reaches its maximum search depth or cannot find valid solutions. Please try refining your request or providing more specific details."
        super().__init__(user_message)


@dataclasses.dataclass
class BaseData:
    workspace: Workspace
    messages: list[Message]
    files: dict[str, str | None] = dataclasses.field(default_factory=dict)
    should_branch: bool = False
    context: str = "default"

    def head(self) -> Message:
        if (num_messages := len(self.messages)) != 1:
            raise ValueError(f"Expected 1 got {num_messages} messages: {self.messages}")
        if self.messages[0].role != "assistant":
            raise ValueError(f"Expected assistant role in message: {self.messages}")
        return self.messages[0]

    @property
    def file_cache_key(self) -> str:
        s = ""
        for file, content in sorted(self.files.items(), key=lambda x: x[0]):
            s += f"{file}:{content}"
        return hashlib.md5(s.encode()).hexdigest()


class BaseActor(statemachine.Actor):
    workspace: Workspace

    async def dump_data(self, data: BaseData) -> object:
        return {
            "messages": [msg.to_dict() for msg in data.messages],
            "files": data.files,
            "should_branch": data.should_branch,
        }

    async def load_data(self, data: dict, workspace: Workspace) -> BaseData:
        for file, content in data["files"].items():
            if content is not None:
                workspace.write_file(file, content)
            else:
                workspace.rm(file)
        messages = [Message.from_dict(msg) for msg in data["messages"]]
        return BaseData(
            workspace, messages, data["files"], data.get("should_branch", False)
        )

    async def dump_node(self, node: Node[BaseData]) -> list[dict]:
        stack, result = [node], []
        while stack:
            node = stack.pop()
            result.append(
                {
                    "id": node._id,
                    "parent": node.parent._id if node.parent else None,
                    "data": await self.dump_data(node.data),
                }
            )
            stack.extend(node.children)
        return result

    async def load_node(self, data: list[dict]) -> Node[BaseData]:
        root = None
        id_to_node: dict[str, Node[BaseData]] = {}
        for item in data:
            parent = id_to_node[item["parent"]] if item["parent"] else None
            workspace = parent.data.workspace if parent else self.workspace
            node_data = await self.load_data(item["data"], workspace.clone())
            node = Node(node_data, parent, item["id"])
            if parent:
                parent.children.append(node)
            else:
                root = node
            id_to_node[item["id"]] = node
        if root is None:
            raise ValueError("Root node not found")
        return root

    async def dump(self) -> object: ...

    async def load(self, data: object): ...


class LLMActor(Protocol):
    llm: AsyncLLM

    async def run_llm(
        self, nodes: list[Node[BaseData]], system_prompt: str | None = None, **kwargs
    ) -> list[Node[BaseData]]:
        async def node_fn(
            node: Node[BaseData], tx: MemoryObjectSendStream[Node[BaseData]]
        ):
            history = [m for n in node.get_trajectory() for m in n.data.messages]
            new_node = Node[BaseData](
                data=BaseData(
                    workspace=node.data.workspace.clone(),
                    messages=[
                        await loop_completion(
                            self.llm, history, system_prompt=system_prompt, **kwargs
                        )
                    ],
                    files={},
                    should_branch=False,
                    context=getattr(node.data, 'context', 'default')
                ),
                parent=node,
            )
            async with tx:
                await tx.send(new_node)

        result = []
        tx, rx = anyio.create_memory_object_stream[Node[BaseData]]()
        async with anyio.create_task_group() as tg:
            for node in nodes:
                tg.start_soon(node_fn, node, tx.clone())
            tx.close()
            async with rx:
                async for new_node in rx:
                    new_node.parent.children.append(new_node)  # pyright: ignore[reportOptionalMemberAccess]
                    result.append(new_node)
        return result


class FileOperationsActor(BaseActor, LLMActor, ABC):
    """Base class for actors that perform file operations with common tools."""

    def __init__(
        self,
        llm: AsyncLLM,
        workspace: Workspace,
        beam_width: int = 3,
        max_depth: int = 30,
        fast_llm: AsyncLLM | None = None,
    ):
        self.llm = llm
        self.fast_llm = fast_llm or get_ultra_fast_llm_client()
        self.workspace = workspace
        self.beam_width = beam_width
        self.max_depth = max_depth
        self.root = None
        logger.info(
            f"Initialized {self.__class__.__name__} with beam_width={beam_width}, max_depth={max_depth}"
        )

    @property
    def base_tools(self) -> list[Tool]:
        """Common file operation tools."""
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
                "name": "write_file",
                "description": "Write content to a file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Edit a file by searching and replacing text",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "search": {"type": "string"},
                        "replace": {"type": "string"},
                        "replace_all": {"type": "boolean", "default": False},
                    },
                    "required": ["path", "search", "replace"],
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
                "name": "complete",
                "description": "Mark the task as complete. This will run tests and type checks to ensure the changes are correct.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    @property
    def additional_tools(self) -> list[Tool]:
        """Additional tools specific to the subclass. Override in subclasses."""
        return []

    @property
    def tools(self) -> list[Tool]:
        """All tools available to this actor."""
        return self.base_tools + self.additional_tools

    def _short_dict_repr(self, d: dict) -> str:
        """Helper function to create short dictionary representations for logging."""
        return ", ".join(
            f"{k}: {v if len(v) < 100 else v[:50] + '...'}"
            for k, v in d.items()
            if isinstance(v, str)
        )

    async def handle_custom_tool(
        self, tool_use: ToolUse, node: Node[BaseData]
    ) -> ToolUseResult:
        """Handle custom tools specific to subclasses. Override in subclasses."""
        raise ValueError(f"Unknown tool: {tool_use.name}")

    async def compact_error_message(self, error_msg: str, max_length: int = 4096) -> str:
        if len(error_msg) <= max_length:
            return error_msg

        original_length = len(error_msg)

        prompt = f"""You need to compact an error message to be concise while keeping the most important information.
        The error message is expected be reduced to be less than {max_length} characters approximately.
        Keep the key error type, file paths, line numbers, and the core issue.
        Remove verbose stack traces, repeated information, and non-essential details not helping to understand the root cause.

        Output the compacted error message wrapped in <error> tags.

        Example:
        <message>
        tests/test_portfolio_service.py:116:9: F841 Local variable `created_positions` is assigned to but never used
            |
        114 |         ]
        115 |
        116 |         created_positions = [portfolio_service.create_position(data) for data in positions_data]
            |         ^^^^^^^^^^^^^^^^^ F841
        117 |
        118 |         all_positions = portfolio_service.get_all_positions()
            |
            = help: Remove assignment to unused variable `created_positions`

        tests/test_portfolio_service.py:271:9: F841 Local variable `position` is assigned to but never used
            |
        269 |     def test_position_update_validation(self, new_db, portfolio_service, sample_position_data):
        270 |         Test position update validation
        271 |         position = portfolio_service.create_position(sample_position_data)
            |         ^^^^^^^^ F841
        272 |
        273 |         # Test invalid shares update
            |
            = help: Remove assignment to unused variable `position`

        Found 16 errors (14 fixed, 2 remaining).
        No fixes available (2 hidden fixes can be enabled with the `--unsafe-fixes` option).

        Test errors:
        ............................FFF.F.F.....F.F.......                       [100%]
        =================================== FAILURES ===================================
        /app/.venv/lib/python3.12/site-packages/nicegui/testing/user.py:141: AssertionError: expected to see at least one element with marker=Asset Type or content=Asset Type on the page:
        /app/.venv/lib/python3.12/site-packages/nicegui/testing/user.py:217: AssertionError: expected to find at least one element with marker=Save or content=Save on the page:
        /app/.venv/lib/python3.12/site-packages/nicegui/testing/user.py:217: AssertionError: expected to find at least one element with marker=Ticker Symbol or content=Ticker Symbol on the page:
        /app/.venv/lib/python3.12/site-packages/nicegui/testing/user.py:141: AssertionError: expected to see at least one element with marker=STOCK or content=STOCK on the page:
        /app/.venv/lib/python3.12/site-packages/nicegui/testing/user.py:217: AssertionError: expected to find at least one element with marker=Ticker Symbol or content=Ticker Symbol on the page:
        /app/tests/test_price_service.py:65: AssertionError: assert 'BTC:BTC' in 'AssetType.BTC:BTC': Decimal('119121.05'), 'AssetType.ETH:ETH': Decimal('3159.2046'), 'AssetType.STOCK:AAPL': Decimal('209.11')
        /app/tests/test_price_service.py:87: AssertionError: assert 'STOCK:AAPL' in 'AssetType.STOCK:AAPL': Decimal('209.11'), 'AssetType.STOCK:INVALID_TICKER_XYZ': None
        =========================== short test summary info ============================
        FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_add_position_dialog_opens
        FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_add_position_form_validation
        FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_add_position_success
        FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_portfolio_table_displays_positions
        FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_portfolio_ui_error_handling
        FAILED tests/test_price_service.py::TestPriceService::test_get_multiple_prices
        FAILED tests/test_price_service.py::TestPriceService::test_get_multiple_prices_with_invalid_ticker
        7 failed, 43 passed, 1 deselected in 6.69s
        </message>


        <error>
        Lint errors:
            tests/test_portfolio_service.py:116:9: F841 Local variable `created_positions` is assigned to but never used
            115 |
            116 |         created_positions = [portfolio_service.create_position(data) for data in positions_data]
                |         ^^^^^^^^^^^^^^^^^ F841
            117 |
            118 |         all_positions = portfolio_service.get_all_positions()

            tests/test_portfolio_service.py:271:9: F841 Local variable `position` is assigned to but never used
            270 |         Test position update validation
            271 |         position = portfolio_service.create_position(sample_position_data)
                |         ^^^^^^^^ F841
            272 |
            273 |         # Test invalid shares update
                |

        Test failures:
            =================================== FAILURES ===================================
            /app/.venv/lib/python3.12/site-packages/nicegui/testing/user.py:141: AssertionError: expected to see at least one element with marker=Asset Type or content=Asset Type on the page:
            /app/.venv/lib/python3.12/site-packages/nicegui/testing/user.py:217: AssertionError: expected to find at least one element with marker=Save or content=Save on the page:
            /app/tests/test_price_service.py:65: AssertionError: assert 'BTC:BTC' in 'AssetType.BTC:BTC': Decimal('119121.05'), 'AssetType.ETH:ETH': Decimal('3159.2046'), 'AssetType.STOCK:AAPL': Decimal('209.11')
            /app/tests/test_price_service.py:87: AssertionError: assert 'STOCK:AAPL' in 'AssetType.STOCK:AAPL': Decimal('209.11'), 'AssetType.STOCK:INVALID_TICKER_XYZ': None
            =========================== short test summary info ============================
            FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_add_position_dialog_opens
            FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_add_position_form_validation
            FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_add_position_success
            FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_portfolio_table_displays_positions
            FAILED tests/test_portfolio_ui.py::TestPortfolioUI::test_portfolio_ui_error_handling
            FAILED tests/test_price_service.py::TestPriceService::test_get_multiple_prices
            FAILED tests/test_price_service.py::TestPriceService::test_get_multiple_prices_with_invalid_ticker
        </error>

        The error message to compact is:
        <message>
        {error_msg}
        </message>
        """

        try:
            result = await self.llm.completion(
                messages=[InternalMessage.from_dict({"role": "user", "content": [{"type": "text", "text": prompt}]})],
                max_tokens=1024,
            )

            if result.content and len(result.content) > 0:
                match result.content[0]:
                    case TextRaw(text=text):
                        compacted = extract_tag(text, "error")
                        if compacted:
                            logger.info(f"Compacted error message size: {len(compacted)}, original size: {original_length}")
                            return compacted.strip()
                    case _:
                        pass
        except Exception as e:
            logger.warning(f"Failed to compact error message using LLM: {e}")

        return error_msg

    async def run_tools(
        self, node: Node[BaseData], user_prompt: str
    ) -> tuple[list[ToolUseResult], bool]:
        """Execute tools for a given node."""
        logger.info(f"Running tools for node {node._id}")
        result, is_completed = [], False

        for block in node.data.head().content:
            if not isinstance(block, ToolUse):
                match block:
                    case TextRaw(text=text):
                        logger.info(f"LLM output: {text}")
                    case _:
                        pass
                continue

            try:
                logger.info(
                    f"Running tool {block.name} with input {self._short_dict_repr(block.input) if isinstance(block.input, dict) else str(block.input)}"
                )

                match block.name:
                    case "read_file":
                        tool_content = await node.data.workspace.read_file(
                            block.input["path"]  # pyright: ignore[reportIndexIssue]
                        )
                        result.append(ToolUseResult.from_tool_use(block, tool_content))

                    case "write_file":
                        path = block.input["path"]  # pyright: ignore[reportIndexIssue]
                        content = block.input["content"]  # pyright: ignore[reportIndexIssue]
                        try:
                            node.data.workspace.write_file(path, content)
                            node.data.files.update({path: content})
                            result.append(ToolUseResult.from_tool_use(block, "success"))
                            logger.debug(f"Written file: {path}")
                        except FileNotFoundError as e:
                            error_msg = (
                                f"Directory not found for file '{path}': {str(e)}"
                            )
                            logger.info(
                                f"File not found error writing file {path}: {str(e)}"
                            )
                            result.append(
                                ToolUseResult.from_tool_use(
                                    block, error_msg, is_error=True
                                )
                            )
                        except PermissionError as e:
                            error_msg = (
                                f"Permission denied writing file '{path}': {str(e)}. Probably this file is out of scope for this particular task."
                            )
                            logger.info(
                                f"Permission error writing file {path}: {str(e)}"
                            )
                            result.append(
                                ToolUseResult.from_tool_use(
                                    block, error_msg, is_error=True
                                )
                            )
                        except ValueError as e:
                            error_msg = str(e)
                            logger.info(f"Value error writing file {path}: {error_msg}")
                            result.append(
                                ToolUseResult.from_tool_use(
                                    block, error_msg, is_error=True
                                )
                            )

                    case "edit_file":
                        path = block.input["path"]  # pyright: ignore[reportIndexIssue]
                        search = block.input["search"]  # pyright: ignore[reportIndexIssue]
                        replace = block.input["replace"]  # pyright: ignore[reportIndexIssue]
                        replace_all = block.input.get("replace_all", False)  # pyright: ignore[reportAttributeAccessIssue]

                        try:
                            original = await node.data.workspace.read_file(path)
                            search_count = original.count(search)
                            match search_count:
                                case 0:
                                    raise ValueError(
                                        f"Search text not found in file '{path}'. Search:\n{search}"
                                    )
                                case 1:
                                    new_content = original.replace(search, replace)
                                    node.data.workspace.write_file(path, new_content)
                                    node.data.files.update({path: new_content})
                                    result.append(
                                        ToolUseResult.from_tool_use(block, "success")
                                    )
                                    logger.debug(f"Applied edit to file: {path}")
                                case num_hits:
                                    if replace_all:
                                        new_content = original.replace(search, replace)
                                        node.data.workspace.write_file(path, new_content)
                                        node.data.files.update({path: new_content})
                                        result.append(
                                            ToolUseResult.from_tool_use(block, f"success - replaced {num_hits} occurrences")
                                        )
                                        logger.debug(f"Applied bulk edit to file: {path} ({num_hits} occurrences)")
                                    else:
                                        raise ValueError(
                                            f"Search text found {num_hits} times in file '{path}' (expected exactly 1). Use replace_all=true to replace all occurrences. Search:\n{search}"
                                        )
                        except FileNotFoundError as e:
                            error_msg = f"File '{path}' not found for editing: {str(e)}"
                            logger.info(
                                f"File not found error editing file {path}: {str(e)}"
                            )
                            result.append(
                                ToolUseResult.from_tool_use(
                                    block, error_msg, is_error=True
                                )
                            )
                        except PermissionError as e:
                            error_msg = (
                                f"Permission denied editing file '{path}': {str(e)}. Probably this file is out of scope for this particular task."
                            )
                            logger.info(
                                f"Permission error editing file {path}: {str(e)}"
                            )
                            result.append(
                                ToolUseResult.from_tool_use(
                                    block, error_msg, is_error=True
                                )
                            )
                        except ValueError as e:
                            error_msg = str(e)
                            logger.info(f"Value error editing file {path}: {error_msg}")
                            result.append(
                                ToolUseResult.from_tool_use(
                                    block, error_msg, is_error=True
                                )
                            )

                    case "delete_file":
                        node.data.workspace.rm(block.input["path"])  # pyright: ignore[reportIndexIssue]
                        node.data.files.update({block.input["path"]: None})  # pyright: ignore[reportIndexIssue]
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
                        node.data.should_branch = True
                        is_completed = check_err is None

                    case _:
                        # Handle custom tools via subclass
                        if isinstance(block.input, dict):
                            custom_result = await self.handle_custom_tool(
                                block, node
                            )
                            result.append(custom_result)
                        else:
                            raise ValueError(
                                f"Invalid input type for tool {block.name}: {type(block.input)}"
                            )

            except FileNotFoundError as e:
                logger.info(f"File not found: {e}")
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except PermissionError as e:
                logger.info(f"Permission error: {e}")
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except ValueError as e:
                logger.info(f"Value error: {e}")
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))
            except Exception as e:
                logger.error(f"Unknown error: {e}")
                result.append(ToolUseResult.from_tool_use(block, str(e), is_error=True))

        return result, is_completed

    async def eval_node(self, node: Node[BaseData], user_prompt: str) -> bool:
        """Evaluate a node by running its tools."""
        tool_calls, is_completed = await self.run_tools(node, user_prompt)
        if tool_calls:
            node.data.messages.append(Message(role="user", content=tool_calls))
        else:
            content = [TextRaw(text="Continue or mark completed via tool call")]
            node.data.messages.append(Message(role="user", content=content))
        return is_completed

    def has_modifications(self, node: Node[BaseData]) -> bool:
        """Check if the node or any of its ancestors have file modifications."""
        cur_node = node
        while cur_node is not None:
            if cur_node.data.files:
                return True
            cur_node = cur_node.parent
        return False

    @abstractmethod
    async def run_checks(self, node: Node[BaseData], user_prompt: str) -> str | None:
        """Run validation checks. Must be implemented by subclasses."""
        pass

    async def dump(self) -> object:
        """Dump the actor state."""
        if self.root is None:
            return []
        return await self.dump_node(self.root)

    async def load(self, data: object):
        """Load the actor state."""
        if not data:
            return
        if not isinstance(data, list):
            raise ValueError(f"Expected list got {type(data)}")
        self.root = await self.load_node(data)
