"""Provider configuration and backend detection for LLM clients."""

import os
from typing import Dict, Any
from llm.anthropic_client import AnthropicLLM
from llm.gemini import GeminiLLM
from llm.lmstudio_client import LMStudioLLM
from llm.openrouter_client import OpenRouterLLM
from llm.openai_client import OpenAILLM

from llm.ollama_client import OllamaLLM


PROVIDERS: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "client": AnthropicLLM,
        "env_vars": ["ANTHROPIC_API_KEY"],
        "requires_base_client": True,
    },
    "bedrock": {
        "client": AnthropicLLM,  # uses AWS client internally
        "env_vars": ["AWS_SECRET_ACCESS_KEY"],
        "requires_base_client": True,
    },
    "gemini": {
        "client": GeminiLLM,
        "env_vars": ["GEMINI_API_KEY"],
    },
    "openai": {
        "client": OpenAILLM,
        "env_vars": ["OPENAI_API_KEY"],
    },
    "ollama": {
        "client": OllamaLLM,
        "env_vars": [],  # works with localhost by default
    },
    "lmstudio": {
        "client": LMStudioLLM,
        "env_vars": [],  # works with localhost by default
    },
    "openrouter": {
        "client": OpenRouterLLM,
        "env_vars": ["OPENROUTER_API_KEY"],
    },
}


def is_backend_available(backend: str) -> bool:
    """Check if a backend has its required environment variables set."""
    config = PROVIDERS.get(backend)
    if not config:
        return False

    # check if all required env vars are set
    required_vars = config.get("env_vars", [])
    if not required_vars:
        return True  # no requirements, always available

    return all(os.getenv(var) for var in required_vars)


def get_backend_for_model(model_name: str) -> str:
    """Determine the backend for a given model name.

    Requires backend:model format:
    - anthropic:claude-sonnet-4-20250514
    - gemini:gemini-2.5-flash-preview-05-20
    - ollama:phi4
    - openrouter:deepseek/deepseek-coder
    - lmstudio:http://localhost:1234
    """
    if ":" not in model_name:
        raise ValueError(
            f"Model '{model_name}' must specify backend using 'backend:model' format "
            f"(e.g., 'anthropic:{model_name}', 'ollama:{model_name}')"
        )

    backend, _ = model_name.split(":", 1)
    if backend not in PROVIDERS:
        raise ValueError(
            f"Unknown backend '{backend}' in model specification '{model_name}'"
        )

    # check if backend has required env vars
    config = PROVIDERS[backend]
    required_vars = config.get("env_vars", [])

    if required_vars:
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            if backend == "bedrock":
                # special case for AWS which has multiple auth methods
                # PREFER_BEDROCK indicates AWS credentials are configured via other means (IAM role, etc)
                if not os.getenv("PREFER_BEDROCK"):
                    raise ValueError(
                        f"Backend '{backend}' requires AWS credentials or PREFER_BEDROCK to be configured"
                    )
            else:
                raise ValueError(
                    f"Backend '{backend}' requires environment variable(s): {', '.join(missing_vars)}"
                )

    return backend


def get_model_mapping(model_name: str, backend: str) -> str:
    """Extract the model part from backend:model format.

    Examples:
    - "anthropic:claude-sonnet" → "claude-sonnet"
    - "lmstudio:http://localhost:1234" → "model"
    - "ollama:phi4" → "phi4"
    """
    # extract model name if backend:model format is used
    if ":" in model_name:
        _, model_part = model_name.split(":", 1)
        # for lmstudio, if model_part is a URL, use a default model name
        if backend == "lmstudio" and (
            model_part.startswith("http://") or model_part.startswith("https://")
        ):
            return "model"  # lmstudio doesn't care about model name
        return model_part

    # shouldn't happen with new format but handle gracefully
    return model_name
