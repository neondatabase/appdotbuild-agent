import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict
from uuid import UUID, uuid4

import coloredlogs
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

if TYPE_CHECKING:
    from asyncpg import Pool

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
    app_dir: NotRequired[str | None]


class TrackerDB:
    """Simple Neon/Postgres tracker for message logging."""

    def __init__(self, wipe_on_start: bool = True):
        load_dotenv()
        self.database_url = os.getenv("DATABASE_URL")
        self.wipe_on_start = wipe_on_start
        self.pool: Pool | None = None

    @property
    def is_connected(self) -> bool:
        return self.pool is not None

    async def init(self) -> None:
        """Initialize DB connection and schema."""
        if not self.database_url or not asyncpg:
            return

        try:
            self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
            assert self.pool is not None

            async with self.pool.acquire() as conn:
                if self.wipe_on_start:
                    await conn.execute("DROP TABLE IF EXISTS messages")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id UUID PRIMARY KEY,
                        role TEXT NOT NULL,
                        message_type TEXT NOT NULL,
                        message TEXT NOT NULL,
                        datetime TIMESTAMP NOT NULL,
                        run_id UUID NOT NULL
                    )
                """)
        except Exception as e:
            print(f"⚠️  DB init failed: {e}", file=sys.stderr)
            self.pool = None

    async def log(self, run_id: UUID, role: str, message_type: str, message: str) -> None:
        if not self.is_connected or self.pool is None:
            return

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO messages (id, role, message_type, message, datetime, run_id) VALUES ($1, $2, $3, $4, $5, $6)",
                    uuid4(),
                    role,
                    message_type,
                    message,
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    run_id,
                )
        except Exception as e:
            print(f"⚠️  DB log failed: {e}", file=sys.stderr)

    async def close(self) -> None:
        """Close DB connection pool."""
        if self.is_connected and self.pool is not None:
            await self.pool.close()


class AppBuilder:
    def __init__(self, app_name: str, wipe_db: bool = True, suppress_logs: bool = False, use_subagents: bool = False):
        self.project_root = Path(__file__).parent.parent.parent
        self.mcp_manifest = self.project_root / "dabgent" / "dabgent_mcp" / "Cargo.toml"

        if not self.mcp_manifest.exists():
            raise RuntimeError(f"dabgent-mcp Cargo.toml not found at {self.mcp_manifest}")

        self.tracker = TrackerDB(wipe_on_start=wipe_db)
        self.run_id: UUID = uuid4()
        self.app_name = app_name
        self.use_subagents = use_subagents
        self.suppress_logs = suppress_logs
        self.app_dir: str | None = None
        # track tool_use_id -> (tool_name, work_dir) to capture app_dir from results
        self._pending_scaffold_calls: dict[str, str] = {}

    def _setup_logging(self) -> None:
        if self.suppress_logs:
            logging.getLogger().setLevel(logging.ERROR)
        else:
            coloredlogs.install(level="INFO")

    async def run_async(self, prompt: str) -> GenerationMetrics:
        self._setup_logging()
        await self.tracker.init()
        self.run_id = uuid4()
        await self.tracker.log(self.run_id, "user", "prompt", f"run_id: {self.run_id}, prompt: {prompt}")

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
        base_instructions = ""

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
            mcp_servers={
                "dabgent": {
                    "type": "stdio",
                    "command": "cargo",
                    "args": [
                        "run",
                        "--manifest-path",
                        str(self.mcp_manifest),
                    ],
                    "env": {},
                }
            },
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
        user_prompt = f"App name: {self.app_name}\nApp directory: ./app/{self.app_name}\n\nTask: {prompt}"

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
                        metrics = {
                            "cost_usd": msg.total_cost_usd,
                            "input_tokens": msg.usage.get("input_tokens", 0),
                            "output_tokens": msg.usage.get("output_tokens", 0),
                            "turns": msg.num_turns,
                            "app_dir": self.app_dir,
                        }
                    case _:
                        pass
        except Exception as e:
            if not self.suppress_logs:
                print(f"\n❌ Error: {e}", file=sys.stderr)
            raise
        finally:
            await self.tracker.close()

        return metrics

    async def _log_tool_use(self, block: ToolUseBlock, truncate) -> None:
        input_dict = block.input or {}
        tool_input = ToolInput(
            subagent_type=input_dict.get("subagent_type", "unknown"),
            description=input_dict.get("description", ""),
            prompt=input_dict.get("prompt", ""),
        )
        if not self.suppress_logs:
            logger.info(f"🚀 Delegating to subagent: {tool_input.subagent_type}")
            logger.info(f"   Task: {tool_input.description}")
            logger.info(f"   Instructions: {truncate(tool_input.prompt, 200)}")
        await self.tracker.log(
            self.run_id,
            "assistant",
            "subagent_invoke",
            f"subagent={tool_input.subagent_type}, task={tool_input.description}, prompt={tool_input.prompt}",
        )

    async def _log_todo_update(self, block: ToolUseBlock, truncate) -> None:
        input_dict = block.input or {}
        todos = input_dict.get("todos", [])

        if not self.suppress_logs and todos:
            completed = sum(1 for t in todos if t.get("status") == "completed")
            in_progress = [t for t in todos if t.get("status") == "in_progress"]

            logger.info(f"📋 Todo update: {completed}/{len(todos)} completed")
            for todo in in_progress:
                logger.info(f"   ▶ {todo.get('activeForm', todo.get('content', 'Unknown'))}")

        await self.tracker.log(
            self.run_id,
            "assistant",
            "todo_update",
            f"todos={len(todos)}, completed={sum(1 for t in todos if t.get('status') == 'completed')}",
        )

    async def _log_generic_tool(self, block: ToolUseBlock, truncate) -> None:
        params = ", ".join(f"{k}={v}" for k, v in (block.input or {}).items())
        if not self.suppress_logs:
            logger.info(f"🔧 Tool: {block.name}({truncate(params, 150)})")
        await self.tracker.log(self.run_id, "assistant", "tool_call", f"{block.name}({params})")

    async def _log_assistant_message(self, message: AssistantMessage) -> None:
        def truncate(text: str, max_len: int = 300) -> str:
            return text if len(text) <= max_len else text[:max_len] + "..."

        for block in message.content:
            match block:
                case TextBlock():
                    if not self.suppress_logs:
                        logger.info(f"💬 {block.text}")
                    await self.tracker.log(self.run_id, "assistant", "text", block.text)
                case ToolUseBlock(name="TodoWrite"):
                    await self._log_todo_update(block, truncate)
                case ToolUseBlock(name="Task"):
                    await self._log_tool_use(block, truncate)
                case ToolUseBlock(name="mcp__dabgent__scaffold_data_app"):
                    if block.input is not None and "work_dir" in block.input:
                        self._pending_scaffold_calls[block.id] = block.input["work_dir"]
                    await self._log_generic_tool(block, truncate)
                case ToolUseBlock():
                    await self._log_generic_tool(block, truncate)

    async def _log_user_message(self, message: UserMessage) -> None:
        def truncate(text: str, max_len: int = 300) -> str:
            return text if len(text) <= max_len else text[:max_len] + "..."

        for block in message.content:
            match block:
                case ToolResultBlock(tool_use_id=tool_id):
                    if tool_id in self._pending_scaffold_calls and not block.is_error:
                        self.app_dir = self._pending_scaffold_calls.pop(tool_id)
                    result_text = str(block.content)
                    if result_text:
                        if not self.suppress_logs:
                            logger.info(f"✅ Tool result: {truncate(result_text)}")
                        await self.tracker.log(self.run_id, "user", "tool_result", result_text)
                case ToolResultBlock(is_error=True):
                    if not self.suppress_logs:
                        logger.warning(f"❌ Tool error: {truncate(str(block.content))}")
                    await self.tracker.log(self.run_id, "user", "tool_error", str(block.content))

    async def _log_result_message(self, message: ResultMessage) -> None:
        def truncate(text: str, max_len: int = 300) -> str:
            return text if len(text) <= max_len else text[:max_len] + "..."

        usage_dict = message.usage or {}
        usage = UsageMetrics(
            input_tokens=usage_dict.get("input_tokens", 0),
            output_tokens=usage_dict.get("output_tokens", 0),
            cache_creation_input_tokens=usage_dict.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=usage_dict.get("cache_read_input_tokens", 0),
        )

        if not self.suppress_logs:
            logger.info(f"🏁 Session complete: {message.num_turns} turns, ${message.total_cost_usd:.4f}")
            logger.info(
                f"   Tokens - in: {usage.input_tokens}, out: {usage.output_tokens}, cache_create: {usage.cache_creation_input_tokens}, cache_read: {usage.cache_read_input_tokens}"
            )
            if message.result:
                logger.info(f"Final result: {truncate(message.result)}")

        await self.tracker.log(
            self.run_id,
            "result",
            "complete",
            f"turns={message.num_turns}, cost=${message.total_cost_usd:.4f}, tokens_in={usage.input_tokens}, tokens_out={usage.output_tokens}, cache_create={usage.cache_creation_input_tokens}, cache_read={usage.cache_read_input_tokens}, result={message.result or 'N/A'}",
        )

    async def _log_message(self, message) -> None:
        match message:
            case AssistantMessage():
                await self._log_assistant_message(message)
            case UserMessage():
                await self._log_user_message(message)
            case ResultMessage():
                await self._log_result_message(message)

    def run(self, prompt: str, wipe_db: bool = True) -> GenerationMetrics:
        self.tracker.wipe_on_start = wipe_db
        return asyncio.run(self.run_async(prompt))
