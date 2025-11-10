"""Trajectory collection for agent runs.

Captures full conversation history (messages, tool calls, results) for analysis.
Works with both Claude SDK and LiteLLM backends.

Storage options:
- JSONL file per app (default): saves to app_dir/trajectory.jsonl
- Neon DB: saves to PostgreSQL database (requires NEON_DATABASE_URL)
- None: trajectory collection disabled
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncpg import Pool


@dataclass
class ToolCall:
    """Tool call in a message"""
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """Tool result in a message"""
    tool_call_id: str
    content: str
    is_error: bool


@dataclass
class Message:
    """Single message in trajectory"""
    role: str  # "system", "user", "assistant", "tool"
    content: str | None
    tool_calls: list[ToolCall] | None
    tool_results: list[ToolResult] | None
    timestamp: datetime
    tokens: dict | None  # optional: {"input": int, "output": int}


@dataclass
class Trajectory:
    """Complete agent trajectory"""
    run_id: str
    app_name: str
    prompt: str
    backend: str  # "claude" or "litellm"
    model: str
    messages: list[Message]
    cost_usd: float
    total_tokens: int
    turns: int
    created_at: datetime


async def save_trajectory(
    trajectory: Trajectory,
    output_file: Path | None = None,
    db_pool: "Pool | None" = None,
) -> None:
    """Save trajectory to JSONL file and/or Neon DB.

    Args:
        trajectory: Trajectory to save
        output_file: Path to JSONL file (if None, skips file export)
        db_pool: asyncpg Pool for Neon DB (if None, skips DB export)
    """
    # save to JSONL file (one message per line for easy streaming analysis)
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w") as f:
            for msg in trajectory.messages:
                f.write(json.dumps(_message_to_dict(msg)) + "\n")

    # save to Neon DB
    if db_pool:
        await _save_to_db(trajectory, db_pool)


def _message_to_dict(message: Message) -> dict:
    """Convert message to JSON-serializable dict"""
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": [asdict(tc) for tc in message.tool_calls] if message.tool_calls else None,
        "tool_results": [asdict(tr) for tr in message.tool_results] if message.tool_results else None,
        "timestamp": message.timestamp.isoformat(),
        "tokens": message.tokens,
    }


async def init_trajectory_db(db_url: str, wipe_on_start: bool = False) -> "Pool | None":
    """Initialize Neon/Postgres database for trajectory storage.

    Args:
        db_url: PostgreSQL connection string (e.g., from NEON_DATABASE_URL)
        wipe_on_start: If True, drops existing trajectories table

    Returns:
        Connection pool or None if initialization failed
    """
    try:
        import asyncpg
    except ImportError:
        return None

    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
        if not pool:
            return None

        async with pool.acquire() as conn:
            # use advisory lock to prevent concurrent schema modifications
            await conn.execute("SELECT pg_advisory_lock(987654321)")
            try:
                async with conn.transaction():
                    if wipe_on_start:
                        await conn.execute("DROP TABLE IF EXISTS trajectories")

                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS trajectories (
                            run_id TEXT PRIMARY KEY,
                            app_name TEXT NOT NULL,
                            prompt TEXT NOT NULL,
                            backend TEXT NOT NULL,
                            model TEXT NOT NULL,
                            messages JSONB NOT NULL,
                            cost_usd REAL NOT NULL,
                            total_tokens INTEGER NOT NULL,
                            turns INTEGER NOT NULL,
                            created_at TIMESTAMP NOT NULL
                        )
                    """)
            finally:
                await conn.execute("SELECT pg_advisory_unlock(987654321)")

        return pool
    except Exception as e:
        print(f"⚠️  Trajectory DB init failed: {e}")
        return None


async def _save_to_db(trajectory: Trajectory, pool: "Pool") -> None:
    """Save trajectory to Neon/Postgres database"""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO trajectories
                (run_id, app_name, prompt, backend, model, messages, cost_usd, total_tokens, turns, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (run_id) DO UPDATE SET
                    messages = EXCLUDED.messages,
                    cost_usd = EXCLUDED.cost_usd,
                    total_tokens = EXCLUDED.total_tokens,
                    turns = EXCLUDED.turns
                """,
                trajectory.run_id,
                trajectory.app_name,
                trajectory.prompt,
                trajectory.backend,
                trajectory.model,
                json.dumps([_message_to_dict(m) for m in trajectory.messages]),
                trajectory.cost_usd,
                trajectory.total_tokens,
                trajectory.turns,
                trajectory.created_at.replace(tzinfo=None),
            )
    except Exception as e:
        print(f"⚠️  Trajectory DB save failed: {e}")
