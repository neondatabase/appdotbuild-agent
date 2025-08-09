"""
Model configuration for LLM categories.

Environment Variable Configuration:
==================================
Override defaults using environment variables with backend:model format:
- LLM_BEST_CODING_MODEL: For best coding tasks (e.g., "ollama:devstral")
- LLM_UNIVERSAL_MODEL: For universal tasks (e.g., "ollama:llama3.3")
- LLM_ULTRA_FAST_MODEL: For ultra fast tasks (e.g., "ollama:phi4")
- LLM_VISION_MODEL: For vision and UI analysis tasks (e.g., "ollama:llama3.2-vision")

Example configurations:
======================
# Local models with Ollama
LLM_BEST_CODING_MODEL=ollama:devstral
LLM_UNIVERSAL_MODEL=ollama:llama3.3
LLM_ULTRA_FAST_MODEL=ollama:phi4
LLM_VISION_MODEL=ollama:llama3.2-vision

# Cloud models (requires API keys)
LLM_BEST_CODING_MODEL=anthropic:claude-sonnet-4-20250514
LLM_UNIVERSAL_MODEL=gemini:gemini-2.5-flash-preview-05-20
LLM_ULTRA_FAST_MODEL=gemini:gemini-2.5-flash-lite-preview-06-17

# OpenRouter (requires OPENROUTER_API_KEY)
LLM_BEST_CODING_MODEL=openrouter:deepseek/deepseek-coder
LLM_UNIVERSAL_MODEL=openrouter:openai/gpt-4o-mini

# LMStudio with custom host
LLM_BEST_CODING_MODEL=lmstudio:http://localhost:1234
"""

import os


class ModelCategory:
    BEST_CODING = "best_coding"  # slow, high quality coding
    UNIVERSAL = "universal"  # medium speed, used for FSM tools
    ULTRA_FAST = "ultra_fast"  # commit names etc
    VISION = "vision"  # vision tasks


# defaults using backend:model format
DEFAULT_MODELS = {
    ModelCategory.BEST_CODING: "anthropic:claude-sonnet-4-20250514",
    ModelCategory.UNIVERSAL: "gemini:gemini-2.5-flash-preview-05-20",
    ModelCategory.ULTRA_FAST: "gemini:gemini-2.5-flash-lite-preview-06-17",
    ModelCategory.VISION: "gemini:gemini-2.5-flash-lite-preview-06-17",
}


def get_model_for_category(category: str) -> str:
    """Get model name for a specific category, with environment variable override support.

    Supports backend:model format in env vars:
    - LLM_BEST_CODING_MODEL=openrouter:deepseek/deepseek-coder
    - LLM_UNIVERSAL_MODEL=lmstudio:http://localhost:1234
    - LLM_ULTRA_FAST_MODEL=ollama:phi4
    """
    env_var = f"LLM_{category.upper()}_MODEL"

    # check for explicit model override first
    if explicit_model := os.getenv(env_var):
        return explicit_model

    # otherwise use regular defaults
    return DEFAULT_MODELS.get(category, DEFAULT_MODELS[ModelCategory.UNIVERSAL])
