import asyncio
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict
from uuid import UUID, uuid4

from claude_agent_sdk import (
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

from cli.utils.shared import ScaffoldTracker, Tracker, setup_logging

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
        output_dir: str | None = None,
        skill_path: str | None = None,
    ):
        load_dotenv()
        self.wipe_db = wipe_db
        self.run_id: UUID = uuid4()
        self.app_name = app_name
        self.suppress_logs = suppress_logs
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "app"
        self.skill_path = Path(skill_path) if skill_path else Path.home() / "dev/cli/experimental/apps-mcp/lib/skill/databricks-apps"
        self.databricks_binary = Path.home() / "dev/cli/cli_linux"
        self.tracker = Tracker(self.run_id, app_name, suppress_logs)
        self.scaffold_tracker = ScaffoldTracker()

    async def run_async(self, prompt: str) -> GenerationMetrics:
        start_time = time.time()

        setup_logging(self.suppress_logs)
        await self.tracker.init(wipe_db=self.wipe_db)

        # check if running in container (skill already mounted by dagger)
        container_skill_path = self.output_dir / ".claude/skills/databricks-apps"
        in_container = container_skill_path.exists()

        if not in_container:
            # copy skill to project directory (local run)
            skill_dest = container_skill_path
            if skill_dest.exists():
                shutil.rmtree(skill_dest)
            skill_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.skill_path, skill_dest)

            # copy databricks binary to bin/ directory
            bin_dir = self.output_dir / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            databricks_dest = bin_dir / "databricks"
            shutil.copy2(self.databricks_binary, databricks_dest)
            databricks_dest.chmod(0o755)

        # patch scripts/db to use databricks binary path
        scripts_db = container_skill_path / "scripts/db"
        db_content = scripts_db.read_text()
        # in container: databricks is at /usr/local/bin/databricks
        # locally: databricks is in bin/ directory (relative to output_dir)
        cli_path = "/usr/local/bin/databricks" if in_container else str(self.output_dir / "bin/databricks")
        db_content = db_content.replace("__DATABRICKS_CLI_PATH__", cli_path)
        scripts_db.write_text(db_content)
        scripts_db.chmod(0o755)

        agents = {}

        base_instructions = """Invoke the databricks-apps skill to build and validate the app.
Be concise and to the point in your responses.
Use up to 10 tools per call to speed up the process.
Never deploy the app, just scaffold and build it.
"""

        disallowed_tools = ["NotebookEdit", "WebSearch", "WebFetch"]

        # prepend bin/ to PATH so databricks binary is found (local run only)
        env: dict[str, str] = {}
        if not in_container:
            bin_dir = self.output_dir / "bin"
            current_path = os.environ.get("PATH", "")
            env = {"PATH": f"{bin_dir}:{current_path}"}

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
            cwd=str(self.output_dir),
            setting_sources=["project"],
            env=env,
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
            # fallback: detect app_dir from filesystem if not tracked
            if not self.scaffold_tracker.app_dir:
                detected = self.scaffold_tracker.detect_from_filesystem(self.output_dir)
                if detected:
                    self.scaffold_tracker.app_dir = detected
                    logger.info(f"📁 Detected app directory from filesystem: {detected}")

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
