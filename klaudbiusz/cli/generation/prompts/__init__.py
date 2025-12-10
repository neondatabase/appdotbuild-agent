"""
Prompt collections for app generation.

For public API, prefer importing from cli.prompts:
    from cli.prompts import get_prompts, DATABRICKS_PROMPTS
"""

from cli.generation.prompts.databricks import PROMPTS as DATABRICKS_PROMPTS
from cli.generation.prompts.databricks_v2 import PROMPTS as DATABRICKS_V2_PROMPTS
from cli.generation.prompts.web import PROMPTS as TEST_PROMPTS

__all__ = [
    "DATABRICKS_PROMPTS",
    "DATABRICKS_V2_PROMPTS",
    "TEST_PROMPTS",
]
