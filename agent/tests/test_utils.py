"""
Test utilities for the agent test suite.
"""

import os

# Load .env file at import time so environment variables are available 
# when pytest.mark.skipif conditions are evaluated
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not available


def is_llm_provider_available() -> bool:
    """Check if any LLM provider is configured and available."""
    # Check for API keys for cloud providers
    if os.getenv("GEMINI_API_KEY"):
        return True
    if os.getenv("ANTHROPIC_API_KEY"):
        return True
    if os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("PREFER_BEDROCK"):
        return True
    
    # Check for Ollama preference (works offline with local Ollama server)
    if os.getenv("PREFER_OLLAMA"):
        return True
    
    # Check for explicit model overrides (indicates user has configured some provider)
    if any(os.getenv(f"LLM_{category}_MODEL") for category in ["FAST", "CODEGEN", "VISION"]):
        return True
    
    return False


def is_databricks_available() -> bool:
    """Check if Databricks credentials are configured and available."""
    # Check for Databricks environment variables
    databricks_host = os.getenv("DATABRICKS_HOST")
    databricks_token = os.getenv("DATABRICKS_TOKEN")
    
    # Both host and token are required for Databricks connection
    return bool(databricks_host and databricks_token)


# Reusable skipif condition for tests that require any LLM provider
def requires_llm_provider() -> bool:
    """Return True if LLM provider is not available, for use with pytest.mark.skipif."""
    return not is_llm_provider_available()

requires_llm_provider_reason = "No LLM provider configured (set GEMINI_API_KEY, ANTHROPIC_API_KEY, PREFER_OLLAMA, or configure specific models)"


# Reusable skipif condition for tests that require Databricks
def requires_databricks() -> bool:
    """Return True if Databricks credentials are not available, for use with pytest.mark.skipif."""
    return not is_databricks_available()

requires_databricks_reason = "No Databricks credentials configured (set DATABRICKS_HOST and DATABRICKS_TOKEN)"