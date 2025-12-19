import json
import re
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


def _extract_json(text: str) -> dict | None:
    """Extract JSON from text, handling markdown code blocks."""
    # try to find JSON in code blocks first
    code_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except json.JSONDecodeError:
            pass

    # try to find raw JSON
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


class GradeResult:
    """Result of grading an app, with buffered logs for deferred printing."""

    def __init__(self, app_name: str):
        self.app_name = app_name
        self.feedback: dict = {}
        self.logs: list[str] = []
        self.trajectory_path: Path | None = None

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def print_logs(self) -> None:
        for line in self.logs:
            print(line)


async def run_grader_single(
    app_dir: Path,
    traj_path: Path,
    grading_skill: Path,
    model: str,
    max_turns: int,
    verbose: bool = False,
) -> GradeResult:
    """Grade a single app using webapp-grading skill.

    Returns GradeResult with feedback and buffered logs.
    """
    result = GradeResult(app_dir.name)

    if verbose:
        result.log(f"    Grading {app_dir.name}...")

    # set up .claude/skills with just webapp-grading for this agent
    claude_skills = app_dir / ".claude" / "skills"
    claude_skills.mkdir(parents=True, exist_ok=True)
    skill_link = claude_skills / "webapp-grading"
    if not skill_link.exists():
        skill_link.symlink_to(grading_skill.resolve())
        if verbose:
            result.log(f"      [skill] webapp-grading -> {grading_skill}")

    user_prompt = f"""Grade the web app.

App directory: {app_dir}
Trajectory file: {traj_path}

Use the webapp-grading skill to analyze and grade this app.
The skill includes a screenshot script - use it to capture the app's UI.
Output your feedback as JSON.
"""

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code"},
        permission_mode="bypassPermissions",
        allowed_tools=["Skill", "Read", "Glob", "Grep", "Bash"],
        max_turns=max_turns,
        model=model,
        cwd=str(app_dir),
        setting_sources=["project"],
    )

    feedback: dict | None = None
    last_text = ""
    turn_count = 0
    trajectory: list[dict] = []

    # trajectory file path
    grader_traj_path = app_dir / "grader_trajectory.jsonl"

    try:
        async for msg in query(prompt=user_prompt, options=options):
            # save to trajectory
            trajectory.append(_serialize_message(msg))

            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        last_text = block.text
                        extracted = _extract_json(block.text)
                        if extracted and "app_name" in extracted:
                            feedback = extracted
                    elif verbose and isinstance(block, ToolUseBlock):
                        tool_info = block.name
                        if block.name == "Bash" and isinstance(block.input, dict):
                            cmd = block.input.get("command", "")[:50]
                            tool_info = f"Bash: {cmd}"
                        elif block.name == "Read" and isinstance(block.input, dict):
                            path = block.input.get("file_path", "")
                            tool_info = f"Read: {path.split('/')[-1]}"
                        result.log(f"      [{tool_info}]")
            elif isinstance(msg, UserMessage):
                turn_count += 1
                if verbose:
                    result.log(f"      [turn {turn_count}]")
            elif isinstance(msg, ResultMessage):
                if verbose:
                    result.log(f"      [done] turns={msg.num_turns} cost=${msg.total_cost_usd:.4f}")

        # save trajectory
        with grader_traj_path.open("w") as f:
            for entry in trajectory:
                f.write(json.dumps(entry) + "\n")
        result.trajectory_path = grader_traj_path

    except Exception as e:
        feedback = {"error": str(e), "app": str(app_dir)}
        if verbose:
            result.log(f"      [error] {e}")

    if feedback is None:
        feedback = _extract_json(last_text)

    if feedback is None:
        feedback = {
            "app_name": app_dir.name,
            "scores": {"code_quality": 0, "ui_ux": 0, "prompt_relevancy": 0, "agent_efficiency": 0},
            "score": 0,
            "type_safe": False,
            "works": False,
            "issues": [{"severity": "high", "category": "skill", "description": "Grader failed to produce feedback"}],
            "successes": [],
            "skill_suggestions": [],
            "trajectory_insights": [],
        }

    result.feedback = feedback
    return result


async def run_grader(
    app_dirs: list[Path],
    trajectory_paths: list[Path],
    grading_skill: Path,
    model: str,
    max_turns: int,
    verbose: bool = False,
) -> list[dict]:
    """Grade apps using webapp-grading skill (sequentially).

    Returns list of feedback dicts, one per app.
    """
    results: list[dict] = []

    for app_dir, traj_path in zip(app_dirs, trajectory_paths):
        grade_result = await run_grader_single(
            app_dir=app_dir,
            traj_path=traj_path,
            grading_skill=grading_skill,
            model=model,
            max_turns=max_turns,
            verbose=verbose,
        )
        grade_result.print_logs()
        results.append(grade_result.feedback)

    return results
