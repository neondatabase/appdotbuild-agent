"""Provider configuration and backend detection for LLM clients."""

import os
from typing import Dict, Any
from llm.anthropic_client import AnthropicLLM
from llm.gemini import GeminiLLM
from llm.lmstudio_client import LMStudioLLM
from llm.openrouter_client import OpenRouterLLM
from llm.openai_client import OpenAILLM
from llm.gonka_client import GonkaLLM

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
    "gonka": {
        "client": GonkaLLM,
        "env_vars": ["GONKA_API_KEY"],
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

    # Special case for Gonka: accepts either GONKA_API_KEY or GONKA_PRIVATE_KEY
    if backend == "gonka":
        return bool(os.getenv("GONKA_PRIVATE_KEY") or os.getenv("GONKA_API_KEY"))

    return all(os.getenv(var) for var in required_vars)


def get_backend_for_model(model_name: str) -> str:
    """Determine the backend for a given model name.

    Requires backend:model format:
    - anthropic:claude-sonnet-4-20250514
    - gemini:gemini-2.5-flash-preview-05-20
    - ollama:phi4
    - openrouter:deepseek/deepseek-coder
    - gonka:Qwen/Qwen3-235B-A22B-Instruct-2507-FP8
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
            elif backend == "gonka":
                # Special case: Gonka accepts either GONKA_PRIVATE_KEY or GONKA_API_KEY
                if not (os.getenv("GONKA_PRIVATE_KEY") or os.getenv("GONKA_API_KEY")):
                    raise ValueError(
                        f"Backend '{backend}' requires GONKA_PRIVATE_KEY or GONKA_API_KEY environment variable"
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
    - "ollama:http://localhost:11434:llama3.3" → "llama3.3"
    """
    # extract model name if backend:model format is used
    if ":" in model_name:
        # for ollama, handle special case of host:model format first
        if backend == "ollama" and model_name.count(":") >= 3:  # ollama:http://host:model
            # find the last colon which separates model from URL
            backend_prefix, rest = model_name.split(":", 1)  # ollama, http://localhost:11434:model
            if "://" in rest:  # contains URL
                url_parts = rest.rsplit(":", 1)  # split on last colon
                if len(url_parts) == 2 and not url_parts[1].startswith("//"):
                    return url_parts[1]  # return model part after URL
        
        # standard handling for other cases
        _, model_part = model_name.split(":", 1)
        
        # for lmstudio, if model_part is a URL, use a default model name
        if backend == "lmstudio" and (model_part.startswith("http://") or model_part.startswith("https://")):
            return "model"  # lmstudio doesn't care about model name
            
        return model_part

    # shouldn't happen with new format but handle gracefully
    return model_name
