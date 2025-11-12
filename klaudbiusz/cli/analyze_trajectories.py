import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import coloredlogs
import fire
import litellm
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


def format_tool_arguments(args: dict) -> str:
    """Format tool arguments as readable JSON."""
    return json.dumps(args, indent=2)


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
                    lines.append(result.get("content", ""))
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


async def aggregate_analyses(analyses: list[tuple[str, str]], model: str) -> str:
    """Aggregate individual analyses to find common patterns (reduce phase)."""
    combined = "\n\n".join([f"## Analysis of {app_name}\n\n{analysis}" for app_name, analysis in analyses])

    prompt = f"""Below are individual analyses of multiple agent execution trajectories.

Your task: Identify common patterns, recurring issues, and systemic problems across all trajectories.

Focus on:
1. What types of errors/struggles appear repeatedly?
2. Which tools or workflows cause consistent friction?
3. What architectural or design issues emerge?
4. What successful patterns are worth reinforcing?

Provide a structured summary with systemic issues and recommendations for improvement where applicable.

Keep in mind that agent itself is not directly controlled, but we can improve the app template scaffoded, validation process and available tools.

{combined}"""

    logger.info("🔄 Aggregating analyses to find common patterns")

    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=16 * 1024,
    )

    return response.choices[0].message.content  # type: ignore[attr-defined]


async def analyze_trajectories_async(
    map_model: str = "anthropic/claude-haiku-4-5",
    reduce_model: str = "anthropic/claude-sonnet-4-5",
    output_file: str = "",
    trajectories_pattern: str = "./app/*/trajectory.jsonl",
):
    """Analyze trajectories using map-reduce approach with LLM."""
    litellm.drop_params = True

    # find all trajectory files
    trajectory_paths = list(Path(".").glob(trajectories_pattern))
    if not trajectory_paths:
        logger.error(f"No trajectories found matching: {trajectories_pattern}")
        return

    logger.info(f"Found {len(trajectory_paths)} trajectories to analyze")

    # map phase: analyze each trajectory concurrently
    trajectory_data = [
        (path.parent.name, format_trajectory_to_markdown(load_trajectory(path))) for path in trajectory_paths
    ]

    tasks = [
        analyze_single_trajectory(trajectory_md, app_name, map_model) for app_name, trajectory_md in trajectory_data
    ]

    analysis_results = await asyncio.gather(*tasks)
    analyses = list(zip([name for name, _ in trajectory_data], analysis_results))

    # reduce phase: aggregate patterns
    final_report = await aggregate_analyses(analyses, reduce_model)

    # output results
    print("\n" + "=" * 80)
    print("TRAJECTORY ANALYSIS REPORT")
    print("=" * 80 + "\n")
    print(final_report)
    print("\n" + "=" * 80 + "\n")

    output_file = output_file or f"/tmp/trajectory_analysis_{datetime.now().strftime('%d%m%y-%H%M%S')}.md"

    # save to file
    output_path = Path(output_file)
    output_path.write_text(final_report)
    logger.info(f"💾 Report saved to: {output_path}")


def cli(
    trajectories_pattern: str = "./app/*/trajectory.jsonl",
    output_file: str | None = "",
    map_model: str = "anthropic/claude-haiku-4-5",
    reduce_model: str = "anthropic/claude-sonnet-4-5",
):
    """Analyze agent trajectories to find friction points and patterns.

    Args:
        trajectories_pattern: Glob pattern to find trajectory files
        model: LiteLLM model identifier
        output_file: Path to save analysis report
    """
    coloredlogs.install(
        level=logging.INFO,
        fmt="%(asctime)s - %(levelname)s - %(message)s",
        logger=logger,
    )

    # suppress litellm logs
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    asyncio.run(analyze_trajectories_async(map_model, reduce_model, output_file, trajectories_pattern))


if __name__ == "__main__":
    load_dotenv()
    fire.Fire(cli)
