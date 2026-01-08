"""Metrics module for Databricks CLI agent trajectories.

This module provides scoring functions specific to Databricks MCP tool usage.
"""

from dataclasses import dataclass
from typing import Any

from sbclaude.schema import (
    MessageModel,
    AssistantMessageModel,
    ToolUseBlockModel,
)


@dataclass
class MetricResult:
    """Result of a metric evaluation."""
    score: float
    feedback: str | None
    details: dict[str, Any] | None = None


def _extract_tool_calls(messages: list[MessageModel]) -> list[ToolUseBlockModel]:
    """Extract all tool call blocks from messages."""
    tool_calls: list[ToolUseBlockModel] = []
    for msg in messages:
        if isinstance(msg, AssistantMessageModel):
            for block in msg.content:
                if isinstance(block, ToolUseBlockModel):
                    tool_calls.append(block)
    return tool_calls


def check_databricks_discover_called(messages: list[MessageModel]) -> MetricResult:
    """Check if databricks_discover MCP tool was called."""
    tool_calls = _extract_tool_calls(messages)

    for call in tool_calls:
        # Match both full MCP name and short name
        if "databricks_discover" in call.name:
            return MetricResult(
                score=0.5,
                feedback=None,
                details={"discover_called": True}
            )

    return MetricResult(
        score=0.0,
        feedback="databricks_discover was not called - agent should discover workspace resources first",
        details={"discover_called": False}
    )


def check_apps_validate_called(messages: list[MessageModel]) -> MetricResult:
    """Check if 'experimental apps-mcp tools validate' was called."""
    tool_calls = _extract_tool_calls(messages)

    for call in tool_calls:
        # Only check invoke_databricks_cli calls
        if "invoke_databricks_cli" not in call.name:
            continue

        args = call.input.get("args", [])

        # Args can be a list or a string
        if isinstance(args, str):
            args_str = args
        elif isinstance(args, list):
            args_str = " ".join(str(a) for a in args)
        else:
            continue

        # Check if validate command is in args
        if "apps-mcp" in args_str and "validate" in args_str:
            return MetricResult(
                score=0.5,
                feedback=None,
                details={"validate_called": True, "args": args_str}
            )

    return MetricResult(
        score=0.0,
        feedback="'experimental apps-mcp tools validate' was not called - agent should validate before deploying",
        details={"validate_called": False}
    )


def evaluate_trajectory(messages: list[MessageModel]) -> dict[str, MetricResult]:
    """Run all Databricks-specific metrics on a trajectory."""
    return {
        "discover_called": check_databricks_discover_called(messages),
        "validate_called": check_apps_validate_called(messages),
    }


def compute_composite_score(metrics: dict[str, MetricResult]) -> float:
    """Compute composite score from Databricks metrics.

    Scoring:
    - databricks_discover called: 0.5 points
    - apps-mcp tools validate called: 0.5 points
    - Total max: 1.0

    Args:
        metrics: Dictionary of metric results from evaluate_trajectory

    Returns:
        Score between 0.0 and 1.0
    """
    score = 0.0

    if "discover_called" in metrics:
        score += metrics["discover_called"].score

    if "validate_called" in metrics:
        score += metrics["validate_called"].score

    return score


def collect_feedback(metrics: dict[str, MetricResult]) -> list[str]:
    """Collect all feedback strings from metrics.

    Args:
        metrics: Dictionary of metric results

    Returns:
        List of non-None feedback strings
    """
    return [
        result.feedback
        for result in metrics.values()
        if result.feedback is not None
    ]


def build_reflection_context(metrics: dict[str, MetricResult]) -> dict[str, Any]:
    """Build a JSON-serializable context dict for reflection.

    Args:
        metrics: Dictionary of metric results from evaluate_trajectory

    Returns:
        Dictionary with all relevant details for the reflection LM
    """
    context: dict[str, Any] = {
        "scores": {name: result.score for name, result in metrics.items()},
        "composite_score": compute_composite_score(metrics),
        "feedback": collect_feedback(metrics),
    }

    # Add details from each metric
    for name, result in metrics.items():
        if result.details:
            context[name] = result.details

    return context
