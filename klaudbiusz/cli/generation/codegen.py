import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict
from uuid import UUID, uuid4

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from dotenv import load_dotenv
from cli.utils.shared import ScaffoldTracker, Tracker, build_mcp_command, setup_logging, validate_mcp_manifest

try:
    import asyncpg  # type: ignore[import-untyped]
except ImportError:
    asyncpg = None

logger = logging.getLogger(__name__)


@dataclass
class UsageMetrics:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass
class ToolInput:
    subagent_type: str = "unknown"
    description: str = ""
    prompt: str = ""


def _parse_agent_definition(agent_file: Path) -> tuple[dict[str, str], str] | None:
    """Parse agent markdown file with YAML frontmatter.

    Returns:
        Tuple of (frontmatter_dict, content) or None if parsing fails
    """
    if not agent_file.exists():
        return None

    content = agent_file.read_text()

    # frontmatter must start and end with ---
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    # parse simple yaml-like frontmatter manually
    frontmatter = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip()

    return frontmatter, parts[2].strip()


class GenerationMetrics(TypedDict):
    cost_usd: float
    input_tokens: int
    output_tokens: int
    turns: int
    generation_time_sec: NotRequired[float]
    app_dir: NotRequired[str | None]


class ClaudeAppBuilder:
    def __init__(
        self,
        app_name: str,
        wipe_db: bool = True,
        suppress_logs: bool = False,
        use_subagents: bool = False,
        mcp_binary: str | None = None,
        mcp_json_path: str | None = None,
        output_dir: str | None = None,
    ):
        load_dotenv()
        self.project_root = Path(__file__).parent.parent.parent
        self.mcp_manifest = validate_mcp_manifest(mcp_binary, self.project_root)

        self.wipe_db = wipe_db
        self.run_id: UUID = uuid4()
        self.app_name = app_name
        self.use_subagents = use_subagents
        self.suppress_logs = suppress_logs
        self.mcp_binary = mcp_binary
        self.mcp_json_path = mcp_json_path
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "app"
        self.tracker = Tracker(self.run_id, app_name, suppress_logs)
        self.scaffold_tracker = ScaffoldTracker()

    async def run_async(self, prompt: str) -> GenerationMetrics:
        start_time = time.time()

        setup_logging(self.suppress_logs, self.mcp_binary)
        await self.tracker.init(wipe_db=self.wipe_db)

        agents = {}
        if self.use_subagents:
            agents_dir = self.project_root / "klaudbiusz" / "agents"
            dataresearch_file = agents_dir / "dataresearch.md"

            if parsed := _parse_agent_definition(dataresearch_file):
                frontmatter, content = parsed
                tools_str = frontmatter.get("tools", "")
                tools = [t.strip() for t in tools_str.split(",")] if tools_str else None

                agents["dataresearch"] = AgentDefinition(
                    description=frontmatter.get("description", ""),
                    prompt=content,
                    tools=tools,
                    model=frontmatter.get("model"),  # type: ignore[arg-type]
                )

        # workflow and template best practices are now in the MCP tool description
        base_instructions = "Use Edda MCP tools to scaffold, build, and test the app as needed.\n Use data from Databricks when relevant.\n"

        if self.use_subagents:
            base_instructions += """When you need to explore Databricks tables, schemas, or execute SQL queries, use the Task tool to delegate to the 'dataresearch' subagent. Do NOT use databricks_* tools directly.\n"""

        base_instructions += """Be concise and to the point in your responses.\n
Use up to 10 tools per call to speed up the process.\n"""

        disallowed_tools = [
            "NotebookEdit",
            "WebSearch",
            "WebFetch",
        ]

        # NOTE: We cannot use disallowed_tools to block Databricks tools from the main agent
        # because disallowed_tools applies globally to ALL agents (including subagents).
        # The CLI doesn't support per-agent tool permissions yet.
        # Instead, we rely on system prompt instructions to enforce delegation.

        command, args = build_mcp_command(self.mcp_binary, self.mcp_manifest, self.mcp_json_path)
        mcp_config = {
            "type": "stdio",
            "command": command,
            "args": args,
            "env": {},
        }

        options = ClaudeAgentOptions(
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": base_instructions,
            },
            permission_mode="bypassPermissions",
            disallowed_tools=disallowed_tools,
            agents=agents,
            max_turns=75,
            mcp_servers={"edda": mcp_config},  # type: ignore[arg-type]
            max_buffer_size=3 * 1024 * 1024,
        )

        if not self.suppress_logs:
            print(f"\n{'=' * 80}")
            print(f"Prompt: {prompt}")
            print(f"{'=' * 80}\n")

        metrics: GenerationMetrics = {
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "turns": 0,
        }

        # inject app_name into user prompt to avoid caching issues with system prompt
        # use absolute path for MCP tool (scaffold_data_app requires absolute path)
        app_dir = self.output_dir / self.app_name
        user_prompt = f"App name: {self.app_name}\nApp directory: {app_dir}\n\nTask: {prompt}"

        try:
            async for message in query(prompt=user_prompt, options=options):
                await self._log_message(message)
                match message:
                    case ResultMessage(total_cost_usd=None):
                        raise RuntimeError("total_cost_usd is None in ResultMessage")
                    case ResultMessage(usage=None):
                        raise RuntimeError("usage is None in ResultMessage")
                    case ResultMessage() as msg:
                        # we've already checked that total_cost_usd and usage are not None
                        assert msg.total_cost_usd is not None
                        assert msg.usage is not None
                        generation_time_sec = time.time() - start_time
                        metrics = {
                            "cost_usd": msg.total_cost_usd,
                            "input_tokens": msg.usage.get("input_tokens", 0),
                            "output_tokens": msg.usage.get("output_tokens", 0),
                            "turns": msg.num_turns,
                            "generation_time_sec": generation_time_sec,
                            "app_dir": self.scaffold_tracker.app_dir,
                        }
                    case _:
                        pass
        except Exception as e:
            if not self.suppress_logs:
                print(f"\n❌ Error: {e}", file=sys.stderr)
            raise
        finally:
            # save trajectory via tracker
            await self.tracker.save(
                prompt=prompt,
                cost_usd=metrics["cost_usd"],
                total_tokens=metrics["input_tokens"] + metrics["output_tokens"],
                turns=metrics["turns"],
                backend="claude",
                model="claude-sonnet-4-5-20250929",
                app_dir=self.scaffold_tracker.app_dir,
            )
            await self.tracker.close()

        # Save generation_metrics.json to app directory for evaluation
        if self.scaffold_tracker.app_dir:
            import json

            metrics_file = Path(self.scaffold_tracker.app_dir) / "generation_metrics.json"
            metrics_file.write_text(
                json.dumps(
                    {
                        "cost_usd": metrics["cost_usd"],
                        "input_tokens": metrics["input_tokens"],
                        "output_tokens": metrics["output_tokens"],
                        "turns": metrics["turns"],
                    },
                    indent=2,
                )
            )

        return metrics

    async def _log_tool_use(self, block: ToolUseBlock, truncate) -> None:
        input_dict = block.input or {}
        tool_input = ToolInput(
            subagent_type=input_dict.get("subagent_type", "unknown"),
            description=input_dict.get("description", ""),
            prompt=input_dict.get("prompt", ""),
        )
        self.tracker.log_subagent_invoke(tool_input.subagent_type, tool_input.description, tool_input.prompt)

    async def _log_todo_update(self, block: ToolUseBlock, truncate) -> None:
        input_dict = block.input or {}
        todos = input_dict.get("todos", [])
        self.tracker.log_todo_update(todos)

    async def _log_generic_tool(self, block: ToolUseBlock, truncate) -> None:
        self.tracker.log_tool_call(block.name, block.input or {}, block.id)

    async def _log_assistant_message(self, message: AssistantMessage) -> None:
        def truncate(text: str, max_len: int = 300) -> str:
            return text if len(text) <= max_len else text[:max_len] + "..."

        for block in message.content:
            match block:
                case TextBlock():
                    self.tracker.log_text("assistant", block.text)
                case ToolUseBlock(name="TodoWrite"):
                    await self._log_todo_update(block, truncate)
                case ToolUseBlock(name="Task"):
                    await self._log_tool_use(block, truncate)
                case ToolUseBlock(name="mcp__edda__scaffold_data_app"):
                    if block.input is not None and "work_dir" in block.input:
                        self.scaffold_tracker.track(block.id, block.input["work_dir"])
                    await self._log_generic_tool(block, truncate)
                case ToolUseBlock():
                    await self._log_generic_tool(block, truncate)

    async def _log_user_message(self, message: UserMessage) -> None:
        def truncate(text: str, max_len: int = 300) -> str:
            return text if len(text) <= max_len else text[:max_len] + "..."

        for block in message.content:
            match block:
                case ToolResultBlock(tool_use_id=tool_id):
                    if not block.is_error:
                        self.scaffold_tracker.resolve(tool_id)
                    result_text = str(block.content)
                    if result_text:
                        self.tracker.log_tool_result(tool_id, result_text, block.is_error or False)

    async def _log_result_message(self, message: ResultMessage) -> None:
        usage_dict = message.usage or {}
        usage = UsageMetrics(
            input_tokens=usage_dict.get("input_tokens", 0),
            output_tokens=usage_dict.get("output_tokens", 0),
            cache_creation_input_tokens=usage_dict.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=usage_dict.get("cache_read_input_tokens", 0),
        )

        self.tracker.log_session_complete(
            turns=message.num_turns,
            cost_usd=message.total_cost_usd or 0.0,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_create=usage.cache_creation_input_tokens,
            cache_read=usage.cache_read_input_tokens,
            result=message.result,
        )

    async def _log_message(self, message) -> None:
        """Route message to appropriate logging handler."""
        match message:
            case AssistantMessage():
                await self._log_assistant_message(message)
            case UserMessage():
                await self._log_user_message(message)
            case ResultMessage():
                await self._log_result_message(message)

    def run(self, prompt: str, wipe_db: bool = True) -> GenerationMetrics:
        self.wipe_db = wipe_db
        return asyncio.run(self.run_async(prompt))
