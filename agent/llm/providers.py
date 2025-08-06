"""Provider configuration and backend detection for LLM clients."""

import os
from typing import Dict, List, Any
from llm.anthropic_client import AnthropicLLM
from llm.gemini import GeminiLLM
from llm.lmstudio_client import LMStudioLLM
from llm.openrouter_client import OpenRouterLLM
from llm.models_config import (
    ANTHROPIC_MODEL_NAMES,
    GEMINI_MODEL_NAMES,
    OLLAMA_MODEL_NAMES,
    OPENROUTER_MODEL_NAMES,
)

try:
    from llm.ollama_client import OllamaLLM
except ImportError:
    OllamaLLM = None


PROVIDERS: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "client": AnthropicLLM,
        "env_vars": ["ANTHROPIC_API_KEY"],
        "models": ANTHROPIC_MODEL_NAMES,
        "requires_base_client": True,
    },
    "bedrock": {
        "client": AnthropicLLM,  # uses AWS client internally
        "env_vars": ["AWS_SECRET_ACCESS_KEY"],
        "models": ANTHROPIC_MODEL_NAMES,
        "requires_base_client": True,
    },
    "gemini": {
        "client": GeminiLLM,
        "env_vars": ["GEMINI_API_KEY"],
        "models": GEMINI_MODEL_NAMES,
    },
    "ollama": {
        "client": OllamaLLM,
        "env_vars": [],  # works with localhost by default
        "models": OLLAMA_MODEL_NAMES,
        "accepts_any_model": True,  # can use any model name
    },
    "lmstudio": {
        "client": LMStudioLLM,
        "env_vars": [],  # works with localhost by default
        "models": [],
        "accepts_any_model": True,  # can use any model name
    },
    "openrouter": {
        "client": OpenRouterLLM,
        "env_vars": ["OPENROUTER_API_KEY"],
        "models": OPENROUTER_MODEL_NAMES,
        "accepts_any_model": True,  # can route to many models
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
    """Determine the best backend for a given model name."""
    # explicit backend preferences via environment variables
    if os.getenv("PREFER_LMSTUDIO"):
        return "lmstudio"
    
    if os.getenv("PREFER_OLLAMA"):
        # ollama can handle both known and unknown models
        if model_name in OLLAMA_MODEL_NAMES or not is_known_model(model_name):
            return "ollama"
    
    if os.getenv("PREFER_OPENROUTER") and is_backend_available("openrouter"):
        return "openrouter"
    
    # check model-specific backends
    for backend, config in PROVIDERS.items():
        if model_name in config.get("models", []):
            if is_backend_available(backend):
                return backend
    
    # special handling for AWS/Bedrock vs Anthropic
    if model_name in ANTHROPIC_MODEL_NAMES:
        if os.getenv("PREFER_BEDROCK") or os.getenv("AWS_SECRET_ACCESS_KEY"):
            return "bedrock"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        # fallback to bedrock for non-trivial AWS configs
        return "bedrock"
    
    # fallback logic for unknown models
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    
    if os.getenv("LMSTUDIO_HOST") or os.getenv("PREFER_LMSTUDIO"):
        return "lmstudio"
    
    if os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_API_BASE"):
        return "ollama"
    
    # default to ollama for unknown models if available
    if OllamaLLM is not None:
        return "ollama"
    
    raise ValueError(
        f"No backend available for model: {model_name}. "
        f"Set one of: ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, "
        f"or configure Ollama/LMStudio."
    )


def is_known_model(model_name: str) -> bool:
    """Check if a model name is in any of our known model lists."""
    all_known_models = (
        ANTHROPIC_MODEL_NAMES +
        GEMINI_MODEL_NAMES +
        OLLAMA_MODEL_NAMES +
        OPENROUTER_MODEL_NAMES
    )
    return model_name in all_known_models


def get_model_mapping(model_name: str, backend: str) -> str:
    """Get the backend-specific model name mapping."""
    from llm.models_config import MODELS_MAP
    
    # if model has a specific mapping for this backend, use it
    if model_name in MODELS_MAP:
        model_config = MODELS_MAP[model_name]
        if backend in model_config:
            return model_config[backend]
    
    # for backends that accept any model, return as-is
    config = PROVIDERS.get(backend, {})
    if config.get("accepts_any_model"):
        return model_name
    
    raise ValueError(f"Model {model_name} not supported on backend {backend}")