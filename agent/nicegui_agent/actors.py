import jinja2
import logging
import anyio
from typing import Callable, Awaitable
from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData, FileOperationsActor
from llm.common import AsyncLLM, Message, TextRaw, Tool, ToolUse, ToolUseResult
from nicegui_agent import playbooks
from core.notification_utils import notify_if_callback, notify_stage
from integrations.dbrx import DatabricksClient

logger = logging.getLogger(__name__)


class NiceguiActor(FileOperationsActor):
    root: Node[BaseData] | None = None

    def __init__(
        self,
        llm: AsyncLLM,
        workspace: Workspace,
        beam_width: int = 3,
        max_depth: int = 30,
        system_prompt: str = playbooks.get_data_model_system_prompt(),
        files_protected: list[str] | None = None,
        files_allowed: list[str] | None = None,
        event_callback: Callable[[str], Awaitable[None]] | None = None,
        databricks_host: str | None = None,
        databricks_token: str | None = None,
    ):
        super().__init__(llm, workspace, beam_width, max_depth)
        self.system_prompt = system_prompt
        self.event_callback = event_callback

        if databricks_host and databricks_token:
            self.databricks_client = DatabricksClient()
            logger.info("Databricks client initialized")
        else:
            self.databricks_client = None
            logger.info("Databricks client not initialized - no credentials provided")
        self.files_protected = files_protected or [
            "pyproject.toml",
            "main.py",
            "tests/conftest.py",
            "tests/test_sqlmodel_smoke.py",
        ]
        self.files_allowed = files_allowed or ["app/", "tests/"]

    async def execute(
        self,
        files: dict[str, str],
        user_prompt: str,
    ) -> Node[BaseData]:
        await notify_stage(
            self.event_callback,
            "🚀 Starting NiceGUI application generation",
            "in_progress",
        )

        workspace = self.workspace.clone()
        if self.databricks_client:
            await workspace.exec_mut(
                ["uv", "add", "databricks-sdk>=0.57.0"]
            )

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

            await notify_if_callback(
                self.event_callback,
                f"🔄 Working on implementation (step {iteration})...",
                "iteration progress",
            )

            logger.info(
                f"Iteration {iteration}: Running LLM on {len(candidates)} candidates"
            )
            nodes = await self.run_llm(
                candidates,
                system_prompt=self.system_prompt,
                tools=self.tools,
                max_tokens=8192,
            )
            logger.info(f"Received {len(nodes)} nodes from LLM")

            for i, new_node in enumerate(nodes):
                logger.info(f"Evaluating node {i + 1}/{len(nodes)}")
                if await self.eval_node(new_node, user_prompt):
                    logger.info(f"Found solution at depth {new_node.depth}")
                    await notify_stage(
                        self.event_callback,
                        "✅ NiceGUI application generated successfully",
                        "completed",
                    )
                    solution = new_node
                    break
        if solution is None:
            logger.error(f"{self.__class__.__name__} failed to find a solution")
            await notify_stage(
                self.event_callback,
                "❌ NiceGUI application generation failed",
                "failed",
            )
            raise ValueError("No solutions found")
        return solution

    def select(self, node: Node[BaseData]) -> list[Node[BaseData]]:
        candidates = []
        all_children = node.get_all_children()
        for n in all_children:
            if n.is_leaf and n.depth <= self.max_depth:
                if n.data.should_branch:
                    effective_beam_width = (
                        1 if len(all_children) > (n.depth + 1) else self.beam_width
                    )  # meaning we already branched once
                    logger.info(
                        f"Selecting candidates with effective beam width: {effective_beam_width}, current depth: {n.depth}/{self.max_depth}"
                    )
                    candidates.extend([n] * effective_beam_width)
                else:
                    candidates.append(n)
        logger.info(f"Selected {len(candidates)} leaf nodes for evaluation")
        return candidates

    @property
    def additional_tools(self) -> list[Tool]:
        """NiceGUI-specific tools."""
        tools = [
            {
                "name": "uv_add",
                "description": "Install additional packages",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "packages": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["packages"],
                },
            },
        ]

        if self.databricks_client:
            tools.extend(
                [
                    {
                        "name": "databricks_list_tables",
                        "description": "List tables in Unity Catalog with optional filtering. Use '*' as wildcard for catalog/schema.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "catalog": {
                                    "type": "string",
                                    "description": "Catalog name",
                                    "default": "samples",
                                },
                                # it has support for '*' as wildcard, but we should not use - too slow!
                                "schema": {
                                    "type": "string",
                                    "description": "Schema name or '*' for all schemas",
                                    "default": "*",
                                },
                                "exclude_inaccessible": {
                                    "type": "boolean",
                                    "description": "Skip tables user cannot access",
                                    "default": True,
                                },
                            },
                            "required": [],
                        },
                    },
                    {
                        "name": "databricks_describe_table",
                        "description": "Get comprehensive table details including metadata, columns, sample data, and row count",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "table_full_name": {
                                    "type": "string",
                                    "description": "Full table name in format 'catalog.schema.table'",
                                },
                                "sample_size": {
                                    "type": "integer",
                                    "description": "Number of sample rows to retrieve",
                                    "default": 10,
                                },
                            },
                            "required": ["table_full_name"],
                        },
                    },
                    {
                        "name": "databricks_execute_query",
                        "description": "Execute a SELECT query on Databricks and get results. Only SELECT queries are allowed for safety.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "SQL SELECT query to execute",
                                },
                                "timeout": {
                                    "type": "integer",
                                    "description": "Query timeout (must be between 5 and 50 or 0 for no timeout)",
                                    "default": 45,
                                },
                            },
                            "required": ["query"],
                        },
                    },
                ]
            )

        return tools

    async def handle_custom_tool(
        self, tool_use: ToolUse, node: Node[BaseData]
    ) -> ToolUseResult:
        """Handle NiceGUI-specific custom tools."""
        assert isinstance(tool_use.input, dict), (
            f"Tool input must be dict, got {type(tool_use.input)}"
        )
        match tool_use.name:
            case "uv_add":
                packages = tool_use.input["packages"]  # pyright: ignore[reportIndexIssue]
                exec_res = await node.data.workspace.exec_mut(
                    ["uv", "add", " ".join(packages)]
                )
                if exec_res.exit_code != 0:
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        f"Failed to add packages: {exec_res.stderr}",
                        is_error=True,
                    )
                else:
                    node.data.files.update(
                        {
                            "pyproject.toml": await node.data.workspace.read_file(
                                "pyproject.toml"
                            )
                        }
                    )
                    return ToolUseResult.from_tool_use(tool_use, "success")

            case "databricks_list_tables":
                if not self.databricks_client:
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        "Databricks credentials not provided. Set databricks_host and databricks_token in constructor.",
                        is_error=True,
                    )

                try:
                    catalog = tool_use.input.get("catalog", "*")  # pyright: ignore[reportIndexIssue]
                    schema = tool_use.input.get("schema", "*")  # pyright: ignore[reportIndexIssue]
                    exclude_inaccessible = tool_use.input.get(
                        "exclude_inaccessible", True
                    )  # pyright: ignore[reportIndexIssue]

                    tables = self.databricks_client.list_tables(
                        catalog=catalog,
                        schema=schema,
                        exclude_inaccessible=exclude_inaccessible,
                    )

                    if not tables:
                        result = f"No accessible tables found with catalog='{catalog}', schema='{schema}'"
                    else:
                        result_lines = [f"Found {len(tables)} accessible tables:"]
                        for table in tables:
                            table_line = f"- {table.full_name} ({table.table_type})"
                            if table.comment:
                                table_line += f" - {table.comment}"
                            result_lines.append(table_line)
                        result = "\n".join(result_lines)

                    return ToolUseResult.from_tool_use(tool_use, result)

                except Exception as e:
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        f"Failed to list tables: {str(e)}",
                        is_error=True,
                    )

            case "databricks_describe_table":
                if not self.databricks_client:
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        "Databricks credentials not provided. Set databricks_host and databricks_token in constructor.",
                        is_error=True,
                    )

                try:
                    table_full_name = tool_use.input["table_full_name"]  # pyright: ignore[reportIndexIssue]
                    sample_size = tool_use.input.get("sample_size", 10)  # pyright: ignore[reportIndexIssue]

                    table_details = self.databricks_client.get_table_details(
                        table_full_name=table_full_name, sample_size=sample_size
                    )

                    # Format comprehensive table information
                    result_lines = [
                        f"Table: {table_details.metadata.full_name}",
                        f"Catalog: {table_details.metadata.catalog}",
                        f"Schema: {table_details.metadata.schema}",
                        f"Name: {table_details.metadata.name}",
                        f"Table Type: {table_details.metadata.table_type}",
                        f"Data Source Format: {table_details.metadata.data_source_format}",
                    ]

                    if table_details.metadata.comment:
                        result_lines.append(
                            f"Comment: {table_details.metadata.comment}"
                        )

                    if table_details.metadata.owner:
                        result_lines.append(f"Owner: {table_details.metadata.owner}")

                    if table_details.row_count is not None:
                        result_lines.append(f"Row Count: {table_details.row_count:,}")

                    if table_details.metadata.storage_location:
                        result_lines.append(
                            f"Storage Location: {table_details.metadata.storage_location}"
                        )

                    # Add column information
                    if table_details.columns:
                        result_lines.append(
                            f"\nColumns ({len(table_details.columns)}):"
                        )
                        for col in table_details.columns:
                            col_info = f"  - {col.name}: {col.data_type}"
                            if col.comment:
                                col_info += f" ({col.comment})"
                            result_lines.append(col_info)

                    # Add sample data if available
                    if (
                        table_details.sample_data is not None
                        and len(table_details.sample_data) > 0
                    ):
                        result_lines.append(
                            f"\nSample Data ({len(table_details.sample_data)} rows):"
                        )
                        # Convert sample data to string representation
                        sample_str = str(table_details.sample_data)
                        result_lines.append(sample_str)

                    result = "\n".join(result_lines)

                    return ToolUseResult.from_tool_use(tool_use, result)

                except Exception as e:
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        f"Failed to describe table: {str(e)}",
                        is_error=True,
                    )

            case "databricks_execute_query":
                if not self.databricks_client:
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        "Databricks credentials not provided. Set databricks_host and databricks_token in constructor.",
                        is_error=True,
                    )

                try:
                    query = tool_use.input["query"]  # pyright: ignore[reportIndexIssue]
                    timeout = tool_use.input.get("timeout", 45)  # pyright: ignore[reportIndexIssue]

                    df = self.databricks_client.execute_query(
                        query=query, timeout=timeout
                    )
                    # format the results
                    if len(df) == 0:
                        result = "Query executed successfully but returned no results."
                    else:
                        result_lines = [
                            f"Query returned {len(df)} rows with {len(df.columns)} columns:",
                            "",
                            "Columns: " + ", ".join(df.columns),
                            "",
                            "Results:",
                        ]

                        # convert DataFrame to a readable string format
                        # limit to first 100 rows for readability
                        display_df = df.head(100) if len(df) > 100 else df
                        result_lines.append(str(display_df))

                        if len(df) > 100:
                            result_lines.append(
                                f"\n... showing first 100 of {len(df)} total rows"
                            )

                        result = "\n".join(result_lines)

                    return ToolUseResult.from_tool_use(tool_use, result)

                except ValueError as e:
                    logger.warning(f"Invalid query: {str(e)}")
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        f"Invalid query: {str(e)}",
                        is_error=True,
                    )
                except Exception as e:
                    logger.warning(f"Failed to execute query: {str(e)}")
                    return ToolUseResult.from_tool_use(
                        tool_use,
                        f"Failed to execute query: {str(e)}",
                        is_error=True,
                    )

            case _:
                return await super().handle_custom_tool(tool_use, node)

    async def run_type_checks(self, node: Node[BaseData]) -> str | None:
        type_check_result = await node.data.workspace.exec(
            ["uv", "run", "pyright", "."]
        )
        if type_check_result.exit_code != 0:
            return f"{type_check_result.stdout}\n{type_check_result.stderr}"
        return None

    async def run_lint_checks(self, node: Node[BaseData]) -> str | None:
        lint_result = await node.data.workspace.exec(
            ["uv", "run", "ruff", "check", ".", "--fix"]
        )
        if lint_result.exit_code != 0:
            return f"{lint_result.stdout}\n{lint_result.stderr}"
        return None

    async def run_tests(self, node: Node[BaseData]) -> str | None:
        pytest_result = await node.data.workspace.exec_with_pg(["uv", "run", "pytest"])
        if pytest_result.exit_code != 0:
            return f"{pytest_result.stdout}\n{pytest_result.stderr}"
        return None

    async def run_sqlmodel_checks(self, node: Node[BaseData]) -> str | None:
        try:
            await node.data.workspace.read_file("app/database.py")
        except FileNotFoundError:
            return "Database configuration missing: app/database.py file not found"
        smoke_test = await node.data.workspace.exec_with_pg(
            ["uv", "run", "pytest", "-m", "sqlmodel", "-v"]
        )
        if smoke_test.exit_code != 0:
            return (
                f"SQLModel validation failed:\n{smoke_test.stdout}\n{smoke_test.stderr}"
            )
        return None

    async def run_checks(self, node: Node[BaseData], user_prompt: str) -> str | None:
        await notify_stage(
            self.event_callback, "🔍 Running validation checks", "in_progress"
        )

        all_errors = ""
        results = {}

        res = await node.data.workspace.exec(
            ["sh", "-c", "echo $DATABRICKS_HOST $DATABRICKS_TOKEN"]
        )
        logger.warning(f"DATABRICKS_HOST: {res.stdout.strip()}")

        async with anyio.create_task_group() as tg:

            async def run_and_store(key, coro):
                """Helper to run a coroutine and store its result in the results dict."""
                try:
                    results[key] = await coro
                except Exception as e:
                    # Catch unexpected exceptions during check execution
                    logger.error(f"Error running check {key}: {e}")
                    results[key] = f"Internal error running check {key}: {e}"

            tg.start_soon(run_and_store, "lint", self.run_lint_checks(node))
            tg.start_soon(run_and_store, "type_check", self.run_type_checks(node))
            tg.start_soon(run_and_store, "tests", self.run_tests(node))
            tg.start_soon(run_and_store, "sqlmodel", self.run_sqlmodel_checks(node))
            tg.start_soon(
                run_and_store, "mocked_files", self.check_for_mocked_files(node)
            )

        if lint_result := results.get("lint"):
            logger.info(f"Lint checks failed: {lint_result}")
            all_errors += f"Lint errors:\n{lint_result}\n"
        if type_check_result := results.get("type_check"):
            logger.info(f"Type checks failed: {type_check_result}")
            all_errors += f"Type errors:\n{type_check_result}\n"
        if test_result := results.get("tests"):
            logger.info(f"Tests failed: {test_result}")
            all_errors += f"Test errors:\n{test_result}\n"
        if sqlmodel_result := results.get("sqlmodel"):
            logger.info(f"SQLModel checks failed: {sqlmodel_result}")
            all_errors += f"SQLModel errors:\n{sqlmodel_result}\n"
        if mocked_files_result := results.get("mocked_files"):
            logger.info(f"Mocked files found: {mocked_files_result}")
            all_errors += (
                f"Error! Disallowed mocked files found:\n{mocked_files_result}\n"
            )

        if all_errors:
            await notify_stage(
                self.event_callback,
                "❌ Validation checks failed - fixing issues",
                "failed",
            )
            errors = await self.compact_error_message(all_errors)
            return errors.strip()

        await notify_stage(
            self.event_callback, "✅ All validation checks passed", "completed"
        )
        return None

    async def check_for_mocked_files(self, node: Node[BaseData]) -> str | None:
        res = await node.data.workspace.exec(
            [
                "sh",
                "-c",
                "grep -r -l -E '(mock|simulated|stub)' app/ tests/ 2>/dev/null | sed 's/^/file /' | sed 's/$/ contains mock/' || true",
            ]
        )
        if res.stdout:
            return res.stdout.strip()
        return None

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
