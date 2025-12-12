import json
from dataclasses import asdict
from pathlib import Path

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


def _serialize_message(msg) -> dict:
    """Serialize a message to a dict for trajectory storage."""
    match msg:
        case AssistantMessage():
            blocks = []
            for block in msg.content:
                match block:
                    case TextBlock():
                        blocks.append({"type": "text", "text": block.text})
                    case ToolUseBlock():
                        blocks.append({"type": "tool_use", "name": block.name, "id": block.id, "input": block.input})
            return {"role": "assistant", "content": blocks}
        case UserMessage():
            blocks = []
            for block in msg.content:
                match block:
                    case ToolResultBlock():
                        content = str(block.content)[:500] if block.content else ""
                        blocks.append({"type": "tool_result", "tool_use_id": block.tool_use_id, "content": content, "is_error": block.is_error})
                    case _:
                        blocks.append({"type": "unknown"})
            return {"role": "user", "content": blocks}
        case ResultMessage():
            return {
                "role": "result",
                "num_turns": msg.num_turns,
                "total_cost_usd": msg.total_cost_usd,
                "is_error": msg.is_error,
            }
        case _:
            return {"role": "unknown", "type": str(type(msg))}


class BuildResult:
    """Result of building an app, with buffered logs for deferred printing."""

    def __init__(self, app_name: str):
        self.app_name = app_name
        self.app_dir: Path | None = None
        self.trajectory_path: Path | None = None
        self.success: bool = False
        self.logs: list[str] = []

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def print_logs(self) -> None:
        for line in self.logs:
            print(line)


async def run_builder(
    prompt: str,
    app_name: str,
    output_dir: Path,
    webapp_creation_skill: Path,
    model: str,
    max_turns: int,
    verbose: bool = False,
) -> BuildResult:
    """Build app using webapp-creation skill.

    Returns BuildResult with app_dir, trajectory_path, and buffered logs.
    """
    result = BuildResult(app_name)
    app_dir = output_dir / app_name
    app_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = app_dir / "trajectory.jsonl"
    result.trajectory_path = trajectory_path

    # set up .claude/skills with just webapp-creation for this agent
    claude_skills = app_dir / ".claude" / "skills"
    claude_skills.mkdir(parents=True, exist_ok=True)
    skill_link = claude_skills / "webapp-creation"
    if not skill_link.exists():
        skill_link.symlink_to(webapp_creation_skill.resolve())
        if verbose:
            result.log(f"      [skill] webapp-creation -> {webapp_creation_skill}")

    user_prompt = f"""Build a web app.

App name: {app_name}
Output directory: {app_dir}

Task: {prompt}

Use the webapp-creation skill to build this app.
"""

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code"},
        permission_mode="bypassPermissions",
        allowed_tools=["Skill", "Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        max_turns=max_turns,
        model=model,
        cwd=str(app_dir),
        setting_sources=["project"],
    )

    trajectory: list[dict] = []
    turn_count = 0
    try:
        async for msg in query(prompt=user_prompt, options=options):
            serialized = _serialize_message(msg)
            trajectory.append(serialized)

            if verbose:
                match msg:
                    case AssistantMessage():
                        for block in msg.content:
                            match block:
                                case TextBlock():
                                    preview = block.text[:100].replace("\n", " ")
                                    if len(block.text) > 100:
                                        preview += "..."
                                    result.log(f"      [text] {preview}")
                                case ToolUseBlock():
                                    tool_info = block.name
                                    if block.name == "Bash" and isinstance(block.input, dict):
                                        cmd = block.input.get("command", "")[:50]
                                        tool_info = f"Bash: {cmd}"
                                    elif block.name in ("Read", "Write", "Edit") and isinstance(block.input, dict):
                                        path = block.input.get("file_path", "")
                                        tool_info = f"{block.name}: {path.split('/')[-1]}"
                                    result.log(f"      [{tool_info}]")
                    case UserMessage():
                        turn_count += 1
                        result.log(f"      [turn {turn_count}]")
                    case ResultMessage():
                        result.log(f"      [done] turns={msg.num_turns} cost=${msg.total_cost_usd:.4f}")
    except Exception as e:
        trajectory.append({"role": "error", "message": str(e)})
        if verbose:
            result.log(f"      [error] {e}")

    # write trajectory
    with open(trajectory_path, "w") as f:
        for entry in trajectory:
            f.write(json.dumps(entry) + "\n")

    # check if app was created
    if (app_dir / "index.html").exists():
        result.app_dir = app_dir
        result.success = True

    return result
