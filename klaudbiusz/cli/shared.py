"""Shared utilities for app generation across different backends.

Contains:
- Tracker: Unified logging and trajectory collection
- Shared data structures and helpers
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from trajectory import Message, ToolCall, ToolResult, Trajectory, init_trajectory_db, save_trajectory

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)


class Tracker:
    """Unified tracker for console logging + trajectory collection + optional DB persistence.

    Replaces the old TrackerDB pattern with a unified interface that:
    1. Logs to console (via logger) for human readability
    2. Collects trajectory messages for analysis
    3. Optionally saves to Neon DB (if NEON_DATABASE_URL set)

    Usage:
        tracker = Tracker(run_id, app_name, suppress_logs=False)
        await tracker.init(wipe_db=False)

        # log events (both console + trajectory)
        tracker.log_text("assistant", "Building dashboard...")
        tracker.log_tool_call("scaffold_data_app", {"app_name": "test"})
        tracker.log_tool_result(tool_id, "Success!")

        await tracker.save(prompt, metrics, backend, model, app_dir)
        await tracker.close()
    """

    def __init__(
        self,
        run_id: UUID,
        app_name: str,
        suppress_logs: bool = False,
    ):
        self.run_id = run_id
        self.app_name = app_name
        self.suppress_logs = suppress_logs
        self.trajectory_messages: list[Message] = []
        self.db_pool: "Pool | None" = None
        self.db_url = os.getenv("NEON_DATABASE_URL")

    async def init(self, wipe_db: bool = False) -> None:
        """Initialize DB connection if NEON_DATABASE_URL is set."""
        if self.db_url:
            self.db_pool = await init_trajectory_db(self.db_url, wipe_on_start=wipe_db)

    async def close(self) -> None:
        """Close DB connection pool."""
        if self.db_pool:
            await self.db_pool.close()

    def log_text(self, role: str, text: str, emoji: str = "💬") -> None:
        """Log text message from assistant or user.

        Args:
            role: "assistant" or "user"
            text: Message text
            emoji: Console emoji prefix
        """
        if not self.suppress_logs:
            logger.info(f"{emoji} {text}")

        self.trajectory_messages.append(Message(
            role=role,
            content=text,
            tool_calls=None,
            tool_results=None,
            timestamp=datetime.now(timezone.utc),
            tokens=None,
        ))

    def log_tool_call(self, tool_name: str, arguments: dict[str, Any], tool_id: str) -> None:
        """Log tool call from assistant.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            tool_id: Unique tool call ID
        """
        # console logging
        if not self.suppress_logs:
            params = ", ".join(f"{k}={v}" for k, v in arguments.items())
            truncated = params if len(params) <= 150 else params[:150] + "..."
            logger.info(f"🔧 Tool: {tool_name}({truncated})")

        # trajectory collection
        self.trajectory_messages.append(Message(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=arguments)],
            tool_results=None,
            timestamp=datetime.now(timezone.utc),
            tokens=None,
        ))

    def log_tool_result(self, tool_id: str, result: str, is_error: bool = False) -> None:
        """Log tool result from environment.

        Args:
            tool_id: Tool call ID this is responding to
            result: Tool result content
            is_error: Whether this is an error result
        """
        # console logging
        if not self.suppress_logs:
            truncated = result if len(result) <= 300 else result[:300] + "..."
            if is_error:
                logger.warning(f"❌ Tool error: {truncated}")
            else:
                logger.info(f"✅ Tool result: {truncated}")

        # trajectory collection
        self.trajectory_messages.append(Message(
            role="tool",
            content=None,
            tool_calls=None,
            tool_results=[ToolResult(tool_call_id=tool_id, content=result, is_error=is_error)],
            timestamp=datetime.now(timezone.utc),
            tokens=None,
        ))

    def log_subagent_invoke(self, subagent_type: str, description: str, prompt: str) -> None:
        """Log subagent delegation (Claude SDK specific)."""
        if not self.suppress_logs:
            logger.info(f"🚀 Delegating to subagent: {subagent_type}")
            logger.info(f"   Task: {description}")
            truncated = prompt if len(prompt) <= 200 else prompt[:200] + "..."
            logger.info(f"   Instructions: {truncated}")

        # add to trajectory as assistant message (contextual info)
        self.trajectory_messages.append(Message(
            role="assistant",
            content=f"[Delegating to subagent: {subagent_type}] {description}",
            tool_calls=None,
            tool_results=None,
            timestamp=datetime.now(timezone.utc),
            tokens=None,
        ))

    def log_todo_update(self, todos: list[dict[str, Any]]) -> None:
        """Log todo list update."""
        if not self.suppress_logs and todos:
            completed = sum(1 for t in todos if t.get("status") == "completed")
            in_progress = [t for t in todos if t.get("status") == "in_progress"]

            logger.info(f"📋 Todo update: {completed}/{len(todos)} completed")
            for todo in in_progress:
                logger.info(f"   ▶ {todo.get('activeForm', todo.get('content', 'Unknown'))}")

        # add to trajectory as assistant message (contextual info)
        summary = f"Todo update: {sum(1 for t in todos if t.get('status') == 'completed')}/{len(todos)} completed"
        self.trajectory_messages.append(Message(
            role="assistant",
            content=f"[{summary}]",
            tool_calls=None,
            tool_results=None,
            timestamp=datetime.now(timezone.utc),
            tokens=None,
        ))

    def log_session_complete(
        self,
        turns: int,
        cost_usd: float,
        input_tokens: int,
        output_tokens: int,
        cache_create: int = 0,
        cache_read: int = 0,
        result: str | None = None,
    ) -> None:
        """Log session completion summary."""
        if not self.suppress_logs:
            logger.info(f"🏁 Session complete: {turns} turns, ${cost_usd:.4f}")
            logger.info(
                f"   Tokens - in: {input_tokens}, out: {output_tokens}, "
                f"cache_create: {cache_create}, cache_read: {cache_read}"
            )
            if result:
                truncated = result if len(result) <= 300 else result[:300] + "..."
                logger.info(f"Final result: {truncated}")

    async def save(
        self,
        prompt: str,
        cost_usd: float,
        total_tokens: int,
        turns: int,
        backend: str,
        model: str,
        app_dir: str | None,
    ) -> None:
        """Save trajectory to JSONL file and/or Neon DB.

        Args:
            prompt: Original user prompt
            cost_usd: Total cost in USD
            total_tokens: Total tokens used
            turns: Number of turns
            backend: Backend name ("claude" or "litellm")
            model: Model identifier
            app_dir: App directory path (if available)
        """
        if not self.trajectory_messages:
            return

        trajectory = Trajectory(
            run_id=str(self.run_id),
            app_name=self.app_name,
            prompt=prompt,
            backend=backend,
            model=model,
            messages=self.trajectory_messages,
            cost_usd=cost_usd,
            total_tokens=total_tokens,
            turns=turns,
            created_at=datetime.now(timezone.utc),
        )

        # save to JSONL file if app_dir exists
        traj_file = Path(app_dir) / "trajectory.jsonl" if app_dir else None

        await save_trajectory(
            trajectory,
            output_file=traj_file,
            db_pool=self.db_pool,
        )

        if not self.suppress_logs and traj_file:
            logger.info(f"💾 Trajectory saved to {traj_file}")


class ScaffoldTracker:
    """Track scaffold_data_app tool calls to capture app directory."""

    def __init__(self):
        self._pending: dict[str, str] = {}
        self.app_dir: str | None = None

    def track(self, tool_id: str, work_dir: str) -> None:
        """Track a scaffold tool call."""
        self._pending[tool_id] = work_dir

    def resolve(self, tool_id: str) -> None:
        """Resolve app_dir from completed scaffold call."""
        if tool_id in self._pending:
            self.app_dir = self._pending.pop(tool_id)


def validate_mcp_manifest(mcp_binary: str | None, project_root: Path) -> Path | None:
    """Validate MCP manifest exists if using cargo run.

    Returns:
        Path to Cargo.toml if using cargo, None if using binary

    Raises:
        RuntimeError: If manifest not found when needed
    """
    if mcp_binary is not None:
        return None

    manifest = project_root / "edda" / "edda_mcp" / "Cargo.toml"
    if not manifest.exists():
        raise RuntimeError(f"edda-mcp Cargo.toml not found at {manifest}")

    return manifest


def setup_logging(suppress_logs: bool, mcp_binary: str | None = None) -> None:
    """Setup logging configuration.

    Args:
        suppress_logs: If True, only show errors
        mcp_binary: Optional MCP binary path for logging
    """
    if suppress_logs:
        logging.getLogger().setLevel(logging.ERROR)
    else:
        try:
            import coloredlogs  # type: ignore[import-untyped]
            coloredlogs.install(level="INFO")
        except ImportError:
            logging.basicConfig(level=logging.INFO)

        if mcp_binary:
            logger.info(f"Using MCP binary: {mcp_binary}")
        else:
            logger.info("Using cargo run for MCP server")


def build_mcp_command(
    mcp_binary: str | None,
    mcp_manifest: Path | None,
    mcp_json_path: str | None = None,
) -> tuple[str, list[str]]:
    """Build MCP server command and arguments.

    Args:
        mcp_binary: Optional path to edda_mcp binary
        mcp_manifest: Path to Cargo.toml (if using cargo run)
        mcp_json_path: Optional path to JSON config file

    Returns:
        Tuple of (command, args)
    """
    if mcp_binary is not None:
        base_args: list[str] = []
        command = mcp_binary
    else:
        if mcp_manifest is None:
            raise ValueError("mcp_manifest required when mcp_binary is None")
        base_args = ["run", "--manifest-path", str(mcp_manifest), "--"]
        command = "cargo"

    # If JSON config file provided, read and pass via --json flag
    if mcp_json_path:
        with open(mcp_json_path) as f:
            config_json = json.dumps(json.load(f))
        args = base_args + ["--json", config_json]
    else:
        args = base_args + ["--with-deployment=false"]

    return (command, args)


def load_subagent_definitions(project_root: Path) -> dict[str, str]:
    """Load subagent definitions from agents directory.

    Args:
        project_root: Project root path

    Returns:
        Dict mapping agent name to agent definition content
    """
    agents_dir = project_root / "klaudbiusz" / "agents"
    agents = {}

    dataresearch_path = agents_dir / "dataresearch.md"
    if dataresearch_path.exists():
        agents["dataresearch"] = dataresearch_path.read_text()

    return agents
