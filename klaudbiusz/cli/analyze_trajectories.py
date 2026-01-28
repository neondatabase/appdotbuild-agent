import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import coloredlogs
import fire
import litellm
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class TrajectoryStep:
    role: str
    content: str | None
    tool_calls: list[dict] | None
    tool_results: list[dict] | None


def load_trajectory(path: Path) -> list[TrajectoryStep]:
    """Load trajectory from JSONL file."""
    steps = []
    with path.open() as f:
        for line in f:
            data = json.loads(line)
            steps.append(
                TrajectoryStep(
                    role=data["role"],
                    content=data.get("content"),
                    tool_calls=data.get("tool_calls"),
                    tool_results=data.get("tool_results"),
                )
            )
    return steps


def truncate_long_strings(value, max_length: int = 8192):
    """Recursively truncate long strings in nested structures."""
    if isinstance(value, str) and len(value) > max_length:
        return f"[truncated {len(value)} chars]"
    elif isinstance(value, dict):
        return {k: truncate_long_strings(v, max_length) for k, v in value.items()}
    elif isinstance(value, list):
        return [truncate_long_strings(item, max_length) for item in value]
    return value


def format_tool_arguments(args: dict) -> str:
    """Format tool arguments as readable JSON, truncating long strings."""
    truncated_args = truncate_long_strings(args)
    return json.dumps(truncated_args, indent=2)


def format_trajectory_to_markdown(steps: list[TrajectoryStep]) -> str:
    """Convert trajectory steps to readable markdown format."""
    lines = []
    lines.append("# Agent Trajectory\n")

    for i, step in enumerate(steps, 1):
        lines.append(f"## Step {i}\n")

        if step.role == "assistant":
            if step.content:
                lines.append("### Agent Reasoning")
                lines.append(step.content)
                lines.append("")

            if step.tool_calls:
                for call in step.tool_calls:
                    lines.append(f"### Tool Call: `{call['name']}`")
                    if call.get("arguments"):
                        lines.append("```json")
                        lines.append(format_tool_arguments(call["arguments"]))
                        lines.append("```")
                    lines.append("")

        elif step.role == "tool":
            if step.tool_results:
                for result in step.tool_results:
                    lines.append("### Tool Result")
                    if result.get("is_error"):
                        lines.append("**⚠️ ERROR**")
                    lines.append("```")
                    content = truncate_long_strings(result.get("content", ""))
                    lines.append(content if isinstance(content, str) else str(content))
                    lines.append("```")
                    lines.append("")

        lines.append("---\n")
    return "\n".join(lines)


async def analyze_single_trajectory(trajectory_md: str, app_name: str, model: str) -> str:
    """Analyze a single trajectory using LLM (map phase)."""
    prompt = f"""Analyze this agent execution trajectory from app: {app_name}

The trajectory shows an AI agent building an application. Your task:
1. Identify where the agent struggled (errors, retries, confusion)
2. Find friction points (slow progress, repeated attempts, inefficient approaches)
3. Note any suboptimal tool usage or decision-making
4. Highlight successful patterns worth noting

Be specific and reference actual steps/tool calls when possible.

Keep in mind that agent itself is not directly controlled, but we can improve the app template scaffoded, validation process and available tools.

{trajectory_md}

Provide a concise analysis focusing on actionable insights."""

    logger.info(f"🔍 Analyzing trajectory: {app_name}")
    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=8 * 1024,
    )

    return response.choices[0].message.content  # type: ignore[attr-defined]


def get_default_skills_path() -> Path | None:
    """Get default skills path, resolving databricks-apps symlink if it exists."""
    skills_dir = Path.home() / ".claude" / "skills"
    databricks_apps = skills_dir / "databricks-apps"

    if databricks_apps.exists():
        # resolve symlink to get actual path
        return databricks_apps.resolve().parent
    return None


def load_evaluation_report(eval_report_path: str | None) -> str:
    """Load evaluation report JSON, drop app_dir and timestamp fields."""
    if not eval_report_path:
        return ""

    eval_path = Path(eval_report_path)
    if not eval_path.exists():
        logger.warning(f"Evaluation report not found: {eval_report_path}")
        return ""

    with eval_path.open() as f:
        eval_data = json.load(f)

    if "apps" in eval_data:
        for app in eval_data["apps"]:
            app.pop("app_dir", None)
            app.pop("timestamp", None)

    return json.dumps(eval_data, indent=2)


async def analyze_with_agent(
    concatenated_analyses: str,
    skills_path: Path | None,
    appkit_path: Path | None,
    eval_report: str = "",
) -> str:
    """Use Claude Agent to analyze trajectories and provide recommendations."""
    logger.info("🤖 Spawning analysis agent to explore sources and provide recommendations")

    disallowed_tools = [
        "Write",
        "Edit",
        "Bash",
        "NotebookEdit",
        "WebSearch",
        "WebFetch",
        "TodoWrite",
        "Task",
        "SlashCommand",
        "Skill",
        "AskUserQuestion",
        "ExitPlanMode",
        "KillShell",
        "BashOutput",
        "Upload",
    ]

    # build optional context sections
    skills_section = ""
    if skills_path:
        skills_section = f"""

## Skills Source

Location: {skills_path}

Explore the skill definitions (SKILL.md files and references/) to identify issues with instructions or guidance.
Skills used: databricks, databricks-apps
"""

    appkit_section = ""
    if appkit_path:
        appkit_section = f"""

## AppKit Source Code

Location: {appkit_path}

Explore the AppKit SDK source to understand available components, hooks, and patterns.
Key areas: packages/appkit-ui (React components), packages/appkit (server SDK), templates/ (app template)
"""

    eval_section = ""
    if eval_report:
        eval_section = f"""

## Evaluation Metrics

{eval_report}
"""

    # build task categories based on available context
    categories = []
    if skills_path:
        categories.append(
            f"{len(categories) + 1}. **Skill improvements**: Missing guidance, unclear instructions, or skill definition issues"
        )
    if appkit_path:
        categories.append(
            f"{len(categories) + 1}. **AppKit/Template improvements**: SDK issues, template structure, missing components, or documentation gaps"
        )
    categories.append(
        f"{len(categories) + 1}. **Root cause analysis**: Why agents failed or struggled in specific trajectories"
    )

    task_description = "\n".join(categories)

    base_instructions = f"""You are analyzing AI agent execution trajectories for a Databricks app generator.

**Your task**: Provide actionable recommendations in these categories:
{task_description}

**Instructions**:
- Focus on systemic issues, not one-off failures
- Be specific: reference file paths, skill names, trajectory patterns
- Format recommendations as markdown with clear sections
- Only analyze context that has been explicitly provided below

---

## Trajectory Analyses

{concatenated_analyses}{skills_section}{appkit_section}{eval_section}

---

Analyze the data and provide your recommendations."""

    options = ClaudeAgentOptions(
        system_prompt=base_instructions,
        permission_mode="bypassPermissions",
        disallowed_tools=disallowed_tools,
        model="claude-opus-4-5",
        allowed_tools=[
            "Read",
            "Glob",
            "Grep",
        ],
        max_turns=50,
    )

    final_result: str | None = None
    async for message in query(prompt="Analyze trajectories and provide recommendations.", options=options):
        match message:
            case AssistantMessage():
                for block in message.content:
                    match block:
                        case TextBlock():
                            text_preview = block.text[:200] if len(block.text) > 200 else block.text
                            logger.info(f"💭 Agent: {text_preview}{'...' if len(block.text) > 200 else ''}")
                        case ToolUseBlock():
                            args = block.input or {}
                            params = ", ".join(f"{k}={str(v)[:200]}" for k, v in args.items())
                            truncated = params if len(params) <= 200 else params[:200] + "..."
                            logger.info(f"🔧 Tool: {block.name}({truncated})")
            case ResultMessage(result=result):
                final_result = result
                logger.info("✅ Agent completed analysis and produced final report")
            case UserMessage():
                for block in message.content:
                    match block:
                        case TextBlock():
                            text_preview = block.text[:200] if len(block.text) > 200 else block.text
                            logger.info(f"👤 User: {text_preview}{'...' if len(block.text) > 200 else ''}")
                        case _:
                            pass
            case SystemMessage():
                pass
            case _:
                logger.warning(f"Unknown message type: {type(message).__name__}")

    if final_result is None:
        raise RuntimeError("Agent did not produce a final report")

    return final_result


async def analyze_trajectories_async(
    skills_path: str | None,
    appkit_path: str | None,
    map_model: str = "anthropic/claude-haiku-4-5",
    output_file: str = "",
    trajectories_pattern: str = "./app/**/trajectory.jsonl",
    eval_report_path: str | None = None,
):
    """Analyze trajectories using map-reduce approach with LLM, then agent-based analysis."""
    litellm.drop_params = True

    # resolve skills path - use provided or detect default
    skills_path_resolved: Path | None = None
    if skills_path:
        skills_path_resolved = Path(skills_path)
    else:
        skills_path_resolved = get_default_skills_path()
        if skills_path_resolved:
            logger.info(f"📚 Using default skills path: {skills_path_resolved}")

    # resolve appkit path - use provided or default
    appkit_path_resolved: Path | None = None
    if appkit_path:
        appkit_path_resolved = Path(appkit_path)
    else:
        default_appkit = Path.home() / "dev" / "appkit"
        if default_appkit.exists():
            appkit_path_resolved = default_appkit
            logger.info(f"📦 Using default AppKit path: {appkit_path_resolved}")

    eval_report = ""
    if eval_report_path:
        logger.info(f"📊 Loading evaluation report: {eval_report_path}")
        eval_report = load_evaluation_report(eval_report_path)

    trajectory_paths = list(Path(".").glob(trajectories_pattern))
    if not trajectory_paths:
        logger.error(f"No trajectories found matching: {trajectories_pattern}")
        return

    logger.info(f"Found {len(trajectory_paths)} trajectories to analyze")

    trajectory_data = [
        (path.parent.name, format_trajectory_to_markdown(load_trajectory(path))) for path in trajectory_paths
    ]
    tasks = [
        analyze_single_trajectory(trajectory_md, app_name, map_model) for app_name, trajectory_md in trajectory_data
    ]

    analysis_results = await asyncio.gather(*tasks)
    analyses = list(zip([name for name, _ in trajectory_data], analysis_results))

    concatenated = "\n\n".join([f"## Analysis of {app_name}\n\n{analysis}" for app_name, analysis in analyses])

    final_report = await analyze_with_agent(
        concatenated, skills_path_resolved, appkit_path_resolved, eval_report
    )

    output_file = output_file or f"/tmp/trajectory_analysis_{datetime.now().strftime('%d%m%y-%H%M%S')}.md"

    output_path = Path(output_file)
    output_path.write_text(final_report)
    logger.info(f"💾 Report saved to: {output_path}")


def cli(
    skills_path: str | None = None,
    appkit_path: str | None = None,
    trajectories_pattern: str = "./app/**/trajectory.jsonl",
    output_file: str = "",
    map_model: str = "anthropic/claude-haiku-4-5",
    eval_report: str | None = None,
):
    """Analyze agent trajectories to find friction points and patterns.

    Args:
        skills_path: Path to skills directory (optional, auto-detected from ~/.claude/skills/)
        appkit_path: Path to AppKit source (optional, defaults to ~/dev/appkit)
        trajectories_pattern: Glob pattern to find trajectory files
        output_file: Path to save analysis report
        map_model: LiteLLM model identifier for individual trajectory analysis
        eval_report: Path to evaluation report JSON (optional)
    """
    coloredlogs.install(
        level=logging.INFO,
        fmt="%(asctime)s - %(levelname)s - %(message)s",
        logger=logger,
    )

    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    asyncio.run(
        analyze_trajectories_async(
            skills_path,
            appkit_path,
            map_model,
            output_file,
            trajectories_pattern,
            eval_report,
        )
    )


if __name__ == "__main__":
    load_dotenv()
    fire.Fire(cli)
