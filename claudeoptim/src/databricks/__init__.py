"""Databricks CLI integration for optimization."""

from databricks.bundle import CliBundle
from databricks.patch import CliPatchData, load_patch_data, apply_patch
from databricks.adapter import DatabricksAdapter, AdapterConfig, Task, CANDIDATE_KEYS
from databricks.metrics import (
    MetricResult,
    evaluate_trajectory,
    compute_composite_score,
    collect_feedback,
    build_reflection_context,
    check_databricks_discover_called,
    check_apps_validate_called,
)

__all__ = [
    "CliBundle",
    "CliPatchData",
    "load_patch_data",
    "apply_patch",
    "Task",
    "DatabricksAdapter",
    "AdapterConfig",
    "CANDIDATE_KEYS",
    "MetricResult",
    "evaluate_trajectory",
    "compute_composite_score",
    "collect_feedback",
    "build_reflection_context",
    "check_databricks_discover_called",
    "check_apps_validate_called",
]
