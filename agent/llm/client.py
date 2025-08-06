"""Simplified client creation for LLM providers."""

import os
from typing import Dict, Any
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock

from llm.common import AsyncLLM
from llm.providers import PROVIDERS, get_model_mapping
from log import get_logger

logger = get_logger(__name__)

try:
    from llm.ollama_client import OllamaLLM
except ImportError:
    OllamaLLM = None


def create_client(backend: str, model_name: str, client_params: Dict[str, Any] | None = None) -> AsyncLLM:
    """Create an LLM client for the specified backend and model.
    
    Args:
        backend: The backend provider name (e.g., 'anthropic', 'gemini', 'ollama')
        model_name: The model name to use
        client_params: Additional parameters to pass to the client constructor
        
    Returns:
        An AsyncLLM client instance
        
    Raises:
        ValueError: If backend is unknown or not available
    """
    if backend not in PROVIDERS:
        raise ValueError(f"Unknown backend: {backend}")
    
    config = PROVIDERS[backend]
    client_class = config["client"]
    client_params = client_params or {}
    
    # get the backend-specific model name
    mapped_model = get_model_mapping(model_name, backend)
    
    # create client based on backend type
    match backend:
        case "bedrock":
            base_client = AsyncAnthropicBedrock(**client_params)
            return client_class(base_client, default_model=mapped_model)
            
        case "anthropic":
            base_client = AsyncAnthropic(**client_params)
            return client_class(base_client, default_model=mapped_model)
            
        case "gemini":
            return client_class(model_name=mapped_model, **client_params)
            
        case "ollama":
            if client_class is None:
                raise ValueError("Ollama backend requires ollama package. Install with: uv sync --group ollama")
            
            # use OLLAMA_HOST/OLLAMA_API_BASE env vars or default
            host = (
                os.getenv("OLLAMA_HOST") or
                os.getenv("OLLAMA_API_BASE") or
                client_params.get("host", "http://localhost:11434")
            )
            return client_class(host=host, model_name=mapped_model)
            
        case "lmstudio":
            # use LMSTUDIO_HOST env var or default
            base_url = (
                os.getenv("LMSTUDIO_HOST") or
                client_params.get("base_url", "http://localhost:1234/v1")
            )
            return client_class(base_url=base_url, model_name=mapped_model)
            
        case "openrouter":
            # openrouter requires an API key
            api_key = os.getenv("OPENROUTER_API_KEY") or client_params.get("api_key")
            if not api_key:
                raise ValueError("OpenRouter backend requires OPENROUTER_API_KEY environment variable")
            
            # optional app attribution
            site_url = os.getenv("OPENROUTER_SITE_URL") or client_params.get("site_url")
            site_name = os.getenv("OPENROUTER_SITE_NAME") or client_params.get("site_name")
            
            return client_class(
                model_name=mapped_model,
                api_key=api_key,
                site_url=site_url,
                site_name=site_name,
            )
            
        case _:
            raise ValueError(f"Unsupported backend: {backend}")