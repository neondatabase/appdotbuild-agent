import anyio
import jinja2
import logging
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass

from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData, FileOperationsActor, AgentSearchFailedException
from llm.common import AsyncLLM, Message, TextRaw, Tool, ToolUse, ToolUseResult
from axum_agent import playbooks
from core.notification_utils import notify_if_callback, notify_stage

logger = logging.getLogger(__name__)


@dataclass
class RustPaths:
    """File path configuration for Rust actor."""

    files_allowed_draft: list[str]
    files_allowed_handlers: list[str]
    files_allowed_ui: list[str]
    files_relevant_draft: list[str]
    files_relevant_handlers: list[str]
    files_relevant_ui: list[str]

    @classmethod
    def default(cls) -> "RustPaths":
        return cls(
            files_allowed_draft=[
                "src/models.rs",
                "src/schema.rs",
                "migrations/",
            ],
            files_allowed_handlers=[
                "src/main.rs",
                "src/handlers.rs",
            ],
            files_allowed_ui=[
                "templates/",
                "src/http/handlers/",
                "src/main.rs",
            ],
            files_relevant_draft=[
                "Cargo.toml",
                "diesel.toml",
                ".env",
            ],
            files_relevant_handlers=[
                "src/models.rs",
                "src/schema.rs",
                "Cargo.toml",
            ],
            files_relevant_ui=[
                "src/models.rs",
                "src/schema.rs",
                "src/http/handlers/",
                "Cargo.toml",
            ],
        )


class RustActor(FileOperationsActor):
    """Rust actor that generates Axum + HTMX applications."""

    def __init__(
        self,
        llm: AsyncLLM,
        vlm: AsyncLLM,
        workspace: Workspace,
        beam_width: int = 3,
        max_depth: int = 30,
        event_callback: Callable[[str, str], Awaitable[None]] | None = None,
        mode: str = "auto",  # "data_model", "handlers", "ui", or "auto"
    ):
        super().__init__(llm, workspace, beam_width, max_depth)
        self.vlm = vlm
        self.event_callback = event_callback
        self.mode = mode

        # User prompt for validation
        self._user_prompt: str = ""

        # File path configuration
        self.paths = RustPaths.default()

    async def execute(
        self,
        files: dict[str, str],
        user_prompt: str,
        feedback: str | None = None,
    ) -> Node[BaseData]:
        """Execute Rust generation or editing based on mode and parameters."""
        self._user_prompt = user_prompt

        # If feedback is provided, route to edit functionality
        if feedback is not None:
            return await self.execute_edit(files, user_prompt, feedback)

        # Update workspace with input files
        self.workspace = self._create_workspace_with_permissions(files, [], [])

        # Execute based on mode
        match self.mode:
            case "data_model":
                return await self._generate_data_model(user_prompt)
            case "handlers":
                return await self._generate_handlers(files, user_prompt)
            case "ui":
                return await self._generate_ui(files, user_prompt)
            case "auto":
                # Legacy auto-detection logic
                has_models = any(
                    f in files for f in ["src/models.rs", "src/schema.rs"]
                )
                if not has_models:
                    return await self._generate_data_model(user_prompt)
                else:
                    return await self._generate_handlers(files, user_prompt)
            case _:
                raise ValueError(f"Unknown mode: {self.mode}")

    async def execute_edit(
        self,
        files: dict[str, str],
        user_prompt: str,
        feedback: str,
    ) -> Node[BaseData]:
        """Execute edit/feedback-based modifications."""
        self._user_prompt = user_prompt

        await notify_stage(
            self.event_callback, "🛠️ Applying requested changes...", "in_progress"
        )

        # Create workspace with input files and permissions
        workspace = self._create_workspace_with_permissions(
            files,
            allowed=self.paths.files_allowed_draft + self.paths.files_allowed_handlers,
            protected=[],
        )
        self.workspace = workspace

        # Build context with relevant files
        context = await self._build_context(workspace, "edit")

        # Prepare edit prompt
        user_prompt_rendered = self._render_prompt(
            "EDIT_ACTOR_USER_PROMPT",
            project_context=context,
            user_prompt=user_prompt,
            feedback=feedback,
        )

        # Create root node for editing
        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        root_node = self._create_node_with_files(workspace, message, files, "edit")

        # Search for solution
        solution = await self._search_single_node(
            root_node, playbooks.EDIT_ACTOR_SYSTEM_PROMPT, True
        )

        if not solution:
            raise AgentSearchFailedException(
                agent_name="RustActor", message="Edit failed to find a solution"
            )

        await notify_stage(
            self.event_callback, "✅ Changes applied successfully!", "completed"
        )

        return solution

    async def _generate_data_model(self, user_prompt: str) -> Optional[Node[BaseData]]:
        """Generate models and schema definitions."""

        await notify_if_callback(
            self.event_callback,
            "🎯 Generating data models and database schema...",
            "draft start",
        )

        # Create draft workspace
        workspace = self.workspace.clone().permissions(
            allowed=self.paths.files_allowed_draft
        )

        # Build context
        context = await self._build_context(workspace, "draft")

        # Prepare prompt
        user_prompt_rendered = self._render_prompt(
            "BACKEND_DRAFT_USER_PROMPT",
            project_context=context,
            user_prompt=user_prompt,
        )

        # Create root node
        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        draft_node = Node(BaseData(workspace, [message], {}, True, "draft"))

        # Search for solution
        solution = await self._search_single_node(
            draft_node, playbooks.BACKEND_DRAFT_SYSTEM_PROMPT, True
        )

        if solution:
            await notify_if_callback(
                self.event_callback, "✅ Data models generated!", "draft complete"
            )
        else:
            raise AgentSearchFailedException(
                agent_name="RustActor",
                message="Draft generation failed - no solution found",
            )

        return solution

    async def _generate_handlers(
        self,
        draft_files: dict[str, str],
        user_prompt: str,
    ) -> Optional[Node[BaseData]]:
        """Generate handlers and main application."""

        await notify_if_callback(
            self.event_callback,
            "🔧 Generating API handlers and routes...",
            "handlers start",
        )

        # Create implementation workspace
        workspace = self._create_workspace_with_permissions(
            draft_files,
            allowed=self.paths.files_allowed_handlers,
            protected=[],
        )

        # Build context
        context = await self._build_context(workspace, "handlers")

        # Prepare prompt
        user_prompt_rendered = self._render_prompt(
            "HANDLERS_USER_PROMPT",
            project_context=context,
            user_prompt=user_prompt,
        )

        # Create root node
        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        handlers_node = Node(BaseData(workspace, [message], {}, True, "handlers"))

        # Search for solution
        solution = await self._search_single_node(
            handlers_node, playbooks.HANDLERS_SYSTEM_PROMPT
        )

        if solution:
            await notify_if_callback(
                self.event_callback,
                "✅ Application handlers generated!",
                "handlers complete",
            )
        else:
            raise AgentSearchFailedException(
                agent_name="RustActor",
                message="Handlers generation failed - no solution found",
            )

        return solution

    async def _generate_ui(
        self,
        files: dict[str, str],
        user_prompt: str,
    ) -> Optional[Node[BaseData]]:
        """Generate UI templates and HTMX components."""

        await notify_if_callback(
            self.event_callback,
            "🎨 Generating UI templates and components...",
            "ui start",
        )

        # Create UI workspace with all existing files
        workspace = self._create_workspace_with_permissions(
            files,
            allowed=["templates/", "src/http/handlers/", "src/main.rs"],
            protected=[],
        )

        # Build context for UI generation
        context = await self._build_context(workspace, "ui")

        # Prepare prompt
        user_prompt_rendered = self._render_prompt(
            "UI_USER_PROMPT",
            project_context=context,
            user_prompt=user_prompt,
        )

        # Create root node
        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        ui_node = Node(BaseData(workspace, [message], {}, True, "ui"))

        # Search for solution
        solution = await self._search_single_node(
            ui_node, playbooks.UI_SYSTEM_PROMPT
        )

        if solution:
            await notify_if_callback(
                self.event_callback,
                "✅ UI templates generated!",
                "ui complete",
            )
        else:
            raise AgentSearchFailedException(
                agent_name="RustActor",
                message="UI generation failed - no solution found",
            )

        return solution

    async def _search_single_node(
        self, root_node: Node[BaseData], system_prompt: str, conditional_tools: bool = False,
    ) -> Optional[Node[BaseData]]:
        """Search for solution from a single node."""
        solution: Optional[Node[BaseData]] = None
        iteration = 0

        while solution is None:
            iteration += 1
            candidates = self._select_candidates(root_node)
            if not candidates:
                logger.info("No candidates to evaluate, search terminated")
                break

            logger.info(
                f"Iteration {iteration}: Running LLM on {len(candidates)} candidates"
            )
            nodes = await self.run_llm(
                candidates,
                system_prompt=system_prompt,
                tools=self.tools + (self.conditional_tools if conditional_tools else []),
                max_tokens=8192,
            )
            logger.info(f"Received {len(nodes)} nodes from LLM")

            for i, new_node in enumerate(nodes):
                logger.info(f"Evaluating node {i + 1}/{len(nodes)}")
                if await self.eval_node(new_node, self._user_prompt):
                    logger.info(f"Found solution at depth {new_node.depth}")
                    solution = new_node
                    break

        return solution

    def _select_candidates(self, node: Node[BaseData]) -> list[Node[BaseData]]:
        """Select candidate nodes for evaluation."""
        if node.is_leaf and node.data.should_branch:
            logger.info(f"Selecting root node {self.beam_width} times (beam search)")
            return [node] * self.beam_width

        all_children = node.get_all_children()
        candidates = []
        for n in all_children:
            if n.is_leaf and n.depth <= self.max_depth:
                if n.data.should_branch:
                    effective_beam_width = (
                        1 if len(all_children) > (n.depth + 1) else self.beam_width
                    )
                    logger.info(
                        f"Selecting candidates with effective beam width: {effective_beam_width}, current depth: {n.depth}/{self.max_depth}"
                    )
                    candidates.extend([n] * effective_beam_width)
                else:
                    candidates.append(n)

        logger.info(f"Selected {len(candidates)} leaf nodes for evaluation")
        return candidates

    async def eval_node(self, node: Node[BaseData], user_prompt: str) -> bool:
        """Evaluate node using base class flow with context-aware checks."""
        tool_calls, is_completed = await self.run_tools(node, user_prompt)
        if tool_calls:
            node.data.messages.append(Message(role="user", content=tool_calls))
        elif not is_completed:
            content = [TextRaw(text="Continue or mark completed via tool call")]
            node.data.messages.append(Message(role="user", content=content))
        return is_completed

    async def run_checks(self, node: Node[BaseData], user_prompt: str) -> str | None:
        """Run context-aware validation checks based on node context."""
        context = node.data.context

        # Run validation based on context
        match context:
            case "draft":
                success = await self._validate_draft(node)
            case "handlers":
                success = await self._validate_handlers(node)
            case "ui":
                success = await self._validate_ui(node)
            case "edit":
                success = await self._validate_edit(node)
            case _:
                logger.warning(f"Unknown context: {context}, skipping validation")
                return None

        # If validation failed, extract error message from last message
        if not success and node.data.messages:
            last_msg = node.data.messages[-1]
            if last_msg.role == "user" and last_msg.content:
                error_texts = []
                for content_item in last_msg.content:
                    if isinstance(content_item, TextRaw):
                        error_texts.append(content_item.text)
                if error_texts:
                    node.data.messages.pop()
                    return "\n".join(error_texts)

        return None if success else "Validation failed"

    async def _validate_draft(self, node: Node[BaseData]) -> bool:
        """Validate draft: Cargo check + Diesel migration."""
        errors = []

        # Run cargo check for compilation errors
        if error := await self.run_cargo_check(node):
            errors.append(error)

        return await self._handle_validation_errors(node, errors)

    async def _validate_handlers(self, node: Node[BaseData]) -> bool:
        """Validate handlers: Cargo check + tests."""
        errors = []

        async with anyio.create_task_group() as tg:

            async def check_cargo():
                if error := await self.run_cargo_check(node):
                    errors.append(error)

            async def check_tests():
                if error := await self.run_test_check(node):
                    errors.append(error)

            tg.start_soon(check_cargo)
            tg.start_soon(check_tests)

        return await self._handle_validation_errors(node, errors)

    async def _validate_ui(self, node: Node[BaseData]) -> bool:
        """Validate UI: Cargo check (for template compilation)."""
        errors = []

        # Check that templates compile correctly (Askama templates are checked during cargo build)
        if error := await self.run_cargo_check(node):
            errors.append(error)

        return await self._handle_validation_errors(node, errors)

    async def _validate_edit(self, node: Node[BaseData]) -> bool:
        """Validate edit: Full validation."""
        await notify_if_callback(
            self.event_callback, "🔍 Validating changes...", "validation start"
        )

        errors = []

        async with anyio.create_task_group() as tg:

            async def check_cargo():
                if error := await self.run_cargo_check(node):
                    errors.append(error)

            async def check_tests():
                if error := await self.run_test_check(node):
                    errors.append(error)

            tg.start_soon(check_cargo)
            tg.start_soon(check_tests)

        if not await self._handle_validation_errors(node, errors):
            return False

        await notify_if_callback(
            self.event_callback, "✅ All validations passed!", "validation success"
        )
        return True

    async def run_cargo_check(self, node: Node[BaseData]) -> str | None:
        """Run Cargo check for compilation errors."""
        result = await node.data.workspace.exec(["cargo", "check", "--quiet"])
        if result.exit_code != 0:
            return f"Cargo check errors:\n{result.stderr}"
        return None


    async def run_test_check(self, node: Node[BaseData]) -> str | None:
        """Run Cargo tests."""
        result = await node.data.workspace.exec_with_pg(["cargo", "test", "--quiet"])
        if result.exit_code != 0:
            return f"Test errors:\n{result.stderr}"
        return None

    def _render_prompt(self, template_name: str, **kwargs) -> str:
        """Render Jinja template with given parameters."""
        jinja_env = jinja2.Environment()
        template = jinja_env.from_string(getattr(playbooks, template_name))
        return template.render(**kwargs)

    def _create_node_with_files(
        self,
        workspace: Workspace,
        message: Message,
        files: dict[str, str],
        context: str = "default",
    ) -> Node[BaseData]:
        """Create a Node with BaseData and copy files to it."""
        node = Node(BaseData(workspace, [message], {}, True, context))
        for file_path, content in files.items():
            node.data.files[file_path] = content
        return node

    async def _handle_validation_errors(
        self, node: Node[BaseData], errors: list[str]
    ) -> bool:
        """Handle validation errors by adding to node messages."""
        if errors:
            error_msg = await self.compact_error_message("\n".join(errors), max_length=1e6)
            node.data.messages.append(
                Message(role="user", content=[TextRaw(error_msg)])
            )
            return False
        return True

    def _create_workspace_with_permissions(
        self,
        files: dict[str, str],
        allowed: list[str],
        protected: list[str] | None = None,
    ) -> Workspace:
        """Create workspace with files and permissions."""
        workspace = self.workspace.clone()
        for file_path, content in files.items():
            workspace.write_file(file_path, content)
        return workspace.permissions(allowed=allowed, protected=protected or [])

    async def _build_context(
        self,
        workspace: Workspace,
        context_type: str,
    ) -> str:
        """Build context for different generation phases."""
        context = []

        # Select relevant files based on context type
        match context_type:
            case "draft":
                relevant_files = self.paths.files_relevant_draft
                allowed_files = self.paths.files_allowed_draft
            case "handlers":
                relevant_files = self.paths.files_relevant_handlers
                allowed_files = self.paths.files_allowed_handlers
            case "ui":
                relevant_files = self.paths.files_relevant_ui
                allowed_files = self.paths.files_allowed_ui
            case "edit":
                relevant_files = (
                    self.paths.files_relevant_draft + self.paths.files_relevant_handlers
                )
                allowed_files = (
                    self.paths.files_allowed_draft + self.paths.files_allowed_handlers
                )
            case _:
                raise ValueError(f"Unknown context type: {context_type}")

        # Add relevant files to context
        for path in relevant_files:
            try:
                content = await workspace.read_file(path)
                context.append(f'\n<file path="{path}">\n{content.strip()}\n</file>\n')
                logger.debug(f"Added {path} to context")
            except Exception:
                pass

        # Add configuration info
        context.append("DATABASE_URL=postgres://postgres:postgres@postgres:5432/postgres")

        if allowed_files:
            context.append(f"Allowed paths and directories: {allowed_files}")

        return "\n".join(context)

    async def handle_custom_tool(
        self, tool_use: ToolUse, node: Node[BaseData]
    ) -> ToolUseResult:
        """Handle Rust-specific custom tools."""
        assert isinstance(tool_use.input, dict), (
            f"Tool input must be dict, got {type(tool_use.input)}"
        )
        match tool_use.name:
            case "cargo_add":
                packages = tool_use.input["packages"]  # pyright: ignore[reportIndexIssue]

                exec_res = await node.data.workspace.exec_mut(
                    ["cargo", "add"] + packages
                )
                if exec_res.exit_code != 0:
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        f"Failed to add packages: {exec_res.stderr}",
                        is_error=True,
                    )
                else:
                    # Update Cargo.toml in files
                    node.data.files.update(
                        {
                            "Cargo.toml": await node.data.workspace.read_file("Cargo.toml"),
                        }
                    )
                    return ToolUseResult.from_tool_use(tool_use, "success")
            case _:
                return await super().handle_custom_tool(tool_use, node)

    @property
    def conditional_tools(self) -> list[Tool]:
        """Conditional tools specific to Rust actor."""
        tools = [
            {
                "name": "cargo_add",
                "description": "Add additional Rust dependencies",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "packages": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["packages"],
                },
            },
        ]
        return tools
