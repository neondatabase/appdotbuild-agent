"""
Public prompts API for klaudbiusz.

Provides easy access to prompt collections for app generation.
Re-exports from cli.generation.prompts for convenience.

Usage:
    from cli.prompts import get_prompts, DATABRICKS_PROMPTS

    # Get default databricks prompts
    prompts = get_prompts()

    # Get specific prompt set
    prompts = get_prompts("databricks_v2")

    # Access prompts directly
    from cli.prompts import DATABRICKS_PROMPTS, DATABRICKS_V2_PROMPTS, TEST_PROMPTS
"""

from cli.generation.prompts.databricks import PROMPTS as DATABRICKS_PROMPTS
from cli.generation.prompts.databricks_v2 import PROMPTS as DATABRICKS_V2_PROMPTS
from cli.generation.prompts.web import PROMPTS as TEST_PROMPTS

PROMPTS: dict[str, dict[str, str]] = {
    "databricks": DATABRICKS_PROMPTS,
    "databricks_v2": DATABRICKS_V2_PROMPTS,
    "test": TEST_PROMPTS,
}


def get_prompts(name: str = "databricks") -> dict[str, str]:
    """Get prompt dictionary by name.

    Args:
        name: Name of the prompt set. One of:
            - "databricks" (default): Original 20 Databricks-focused prompts
            - "databricks_v2": Realistic human-style requests (30+ prompts)
            - "test": Simple web app prompts for testing

    Returns:
        Dictionary mapping app_name -> prompt_text

    Raises:
        KeyError: If prompt set name is not found
    """
    if name not in PROMPTS:
        available = ", ".join(PROMPTS.keys())
        raise KeyError(f"Unknown prompt set: {name}. Available: {available}")
    return PROMPTS[name]


def list_prompt_sets() -> list[str]:
    """List available prompt set names."""
    return list(PROMPTS.keys())


__all__ = [
    "PROMPTS",
    "DATABRICKS_PROMPTS",
    "DATABRICKS_V2_PROMPTS",
    "TEST_PROMPTS",
    "get_prompts",
    "list_prompt_sets",
]
